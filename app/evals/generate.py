"""Sinh eval_cases bằng Gemini (prompt khác enrich), lọc rò rỉ so với sample_questions/aliases,
phân tầng dev/test theo category."""
from __future__ import annotations

import random

import numpy as np

from app import repo
from app.catalog.texts import fmt_price, product_attrs
from app.gemini.pool import BaseGemini
from app.ingest.vectors import RateLimiter
from app.text.normalize import normalize_query

CATEGORIES = ["name", "alias", "asr", "no_accent", "use_case", "price", "numeric_attr", "multi_turn",
              "ambiguous", "compare", "out_of_scope"]

SYSTEM = (
    "Bạn tạo bộ câu KIỂM THỬ cho hệ thống tìm sản phẩm của callbot tiếng Việt. Câu phải giống lời khách thật "
    "qua điện thoại (văn nói, có thể có từ đệm 'dạ', 'ừm', 'cho em hỏi'), KHÔNG được chép lại hay diễn đạt "
    "gần giống các câu hỏi mẫu / tên khác đã có (danh sách cấm bên dưới).\n"
    "Loại câu (category):\n"
    "- name: gọi tên sản phẩm (có thể thiếu một phần tên)\n"
    "- alias: gọi kiểu viết tắt / tên đời thường\n"
    "- asr: câu bị nhận dạng giọng nói sai (sai thanh, tên nước ngoài phiên âm, số đọc bằng chữ)\n"
    "- no_accent: câu gõ không dấu\n"
    "- use_case: mô tả nhu cầu, không nêu tên\n"
    "- price: hỏi theo khoảng giá + loại sản phẩm\n"
    "- numeric_attr: hỏi theo thông số có số (dung tích, kích thước, số phòng...)\n"
    "- multi_turn: câu tiếp nối, cần context.previous_text và previous_product_ids\n"
    "- ambiguous: câu chung chung khớp với 2-4 sản phẩm gần giống nhau (expected_status=ambiguous, liệt kê hết)\n"
    "- compare: so sánh 2 sản phẩm (expected_status=ambiguous, liệt kê cả 2)\n"
    "- out_of_scope: không liên quan cửa hàng (expected_product_ids rỗng, expected_status=out_of_scope)\n"
    "expected_status: matched nếu câu chỉ đúng 1 sản phẩm; no_match nếu hỏi sản phẩm cửa hàng KHÔNG có."
)


def _schema(ids: list[int]) -> dict:
    return {"type": "object", "properties": {"cases": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
            "expected_product_ids": {"type": "array", "items": {"type": "integer", "enum": ids}},
            "expected_status": {"type": "string", "enum": ["matched", "ambiguous", "no_match", "out_of_scope"]},
            "previous_text": {"type": ["string", "null"]},
            "previous_product_ids": {"type": "array", "items": {"type": "integer", "enum": ids}},
        },
        "required": ["query", "category", "expected_product_ids", "expected_status"]}}}, "required": ["cases"]}


async def generate_cases(pool, gem: BaseGemini, svc, slug: str, *, per_product: int = 2, extra_general: int = 20,
                         timeout_ms: int, per_minute: int, seed: int = 7, progress=None, batch: int = 6) -> dict:
    demo = await repo.get_demo(pool, slug)
    defs = await repo.list_defs(pool, demo["id"])
    products = await repo.list_products(pool, demo["id"])
    ids = [p["id"] for p in products]
    banned = [q for p in products for q in (p.get("sample_questions") or [])]
    banned_norm = {normalize_query(q)[0] for q in banned}
    catalog = "\n".join(
        f"[{p['id']}] {p['name']} | {p.get('brand') or ''} | {p.get('category') or ''} | "
        f"{fmt_price(p.get('price'), p.get('price_unit'))} | "
        + "; ".join(f"{a['label']}: {a['display']}" for a in product_attrs(p, defs)[:6])
        for p in products)
    limiter = RateLimiter(per_minute)
    raw_cases: list[dict] = []
    groups = [ids[i:i + batch] for i in range(0, len(ids), batch)]
    for gi, g in enumerate(groups + [[]]):
        await limiter.acquire(1)
        if g:
            ask = (f"Tạo {per_product * len(g)} câu cho các sản phẩm {g} (mỗi sản phẩm ~{per_product} câu, "
                   "trải đều các category name/alias/asr/no_accent/use_case/price/numeric_attr/multi_turn).")
        else:
            ask = (f"Tạo {extra_general} câu chung: khoảng 40% ambiguous/compare, 30% out_of_scope, 30% no_match "
                   "(hỏi sản phẩm cùng ngành mà cửa hàng không bán).")
        contents = (f"Danh mục cửa hàng {demo['name']}:\n{catalog}\n\nCâu CẤM dùng lại:\n"
                    + "\n".join(f"- {q}" for q in banned[:300]) + f"\n\n{ask}")
        raw = await gem.generate_json(system=SYSTEM, contents=contents, schema=_schema(ids), call_type="gen_eval",
                                      timeout_ms=timeout_ms, demo_id=demo["id"], max_output_tokens=6000,
                                      temperature=0.7)
        raw_cases += (raw or {}).get("cases") or []
        if progress:
            await progress(90.0 * (gi + 1) / (len(groups) + 1))

    # lọc rò rỉ: trùng chuẩn hoá hoặc cosine >= 0.95 với vector câu hỏi mẫu
    idx = svc.indexes.get(slug)
    qvecs = None
    if idx is not None and idx.Vf32 is not None:
        qvecs = idx.Vf32[idx.vec_kind == 3]
    kept, dropped = [], []
    seen = set()
    texts = [c["query"] for c in raw_cases]
    embs = None
    if qvecs is not None and len(qvecs) and texts:
        embs = await gem.embed(texts, "RETRIEVAL_QUERY", call_type="gen_eval", timeout_ms=timeout_ms,
                               demo_id=demo["id"], model=idx.embed_model, dim=demo["embed_dim"])
    for i, c in enumerate(raw_cases):
        qn = normalize_query(c["query"])[0]
        if qn in banned_norm or qn in seen:
            dropped.append({**c, "drop_reason": "duplicate"})
            continue
        if embs is not None and float(np.max(qvecs @ embs[i])) >= 0.95:
            dropped.append({**c, "drop_reason": "leak_cosine"})
            continue
        seen.add(qn)
        ctx = None
        if c.get("previous_text") or c.get("previous_product_ids"):
            ctx = {"previous_text": c.get("previous_text"), "previous_product_ids": c.get("previous_product_ids") or []}
        kept.append({"query": c["query"], "category": c["category"], "context": ctx,
                     "expected_product_ids": sorted(set(c.get("expected_product_ids") or [])),
                     "expected_status": c["expected_status"], "source": "ai"})
    assign_splits(kept, seed=seed)
    return {"cases": kept, "dropped": dropped, "n_raw": len(raw_cases)}


def assign_splits(cases: list[dict], dev_ratio: float = 0.4, seed: int = 7) -> None:
    rnd = random.Random(seed)
    by_cat: dict[str, list[dict]] = {}
    for c in cases:
        by_cat.setdefault(c.get("category") or "other", []).append(c)
    for lst in by_cat.values():
        rnd.shuffle(lst)
        k = round(len(lst) * dev_ratio)
        for j, c in enumerate(lst):
            c["split"] = "dev" if j < k else "test"
