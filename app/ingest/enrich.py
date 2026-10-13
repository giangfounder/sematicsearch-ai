"""Làm giàu dữ liệu bằng Gemini: aliases (gồm lỗi ASR tiếng Việt), use_cases, sample_questions.
Chỉ điền trường trống hoặc trường được chọn ghi đè; kết quả dry_run lưu trong jobs.result để duyệt."""
from __future__ import annotations

from app import repo
from app.catalog.texts import fmt_price, product_attrs
from app.db import bump_version
from app.gemini.pool import BaseGemini
from app.ingest.vectors import RateLimiter

FIELDS = ["aliases", "use_cases", "sample_questions"]

SYSTEM = (
    "Bạn là chuyên gia dữ liệu cho callbot/chatbot bán hàng tiếng Việt. Với mỗi sản phẩm, sinh:\n"
    "1) aliases (5-12): cách khách GỌI sản phẩm khi nói chuyện điện thoại: tên rút gọn, viết tắt, không dấu, "
    "tên nước ngoài đọc kiểu Việt (iPhone -> 'ai phôn', Samsung -> 'sam sung', Panasonic -> 'pa na sô níc'), "
    "lỗi nhận dạng giọng nói hay gặp (sai thanh: 'tủ lạnh' -> 'tủ lãnh'; nhầm âm đầu/cuối; số đọc thành chữ: "
    "'55 inch' -> 'năm lăm in'). Không thêm tên của sản phẩm khác.\n"
    "2) use_cases (3-6): sản phẩm phù hợp cho ai, dùng làm gì (cụm ngắn, ví dụ 'gia đình 4-5 người').\n"
    "3) sample_questions (5-10): câu khách thật hay hỏi khi muốn mua ĐÚNG sản phẩm này, đa dạng: gọi tên, "
    "theo nhu cầu, theo giá, theo thuộc tính, văn nói tự nhiên có từ đệm. Mỗi câu phải đủ thông tin để phân biệt "
    "sản phẩm này với sản phẩm cùng loại.\n"
    "Chỉ dựa trên dữ liệu được cung cấp, không bịa thông số."
)


def _schema(ids: list[int]) -> dict:
    arr = {"type": "array", "items": {"type": "string"}}
    return {"type": "object", "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"product_id": {"type": "integer", "enum": ids}, "aliases": {**arr, "maxItems": 12},
                       "use_cases": {**arr, "maxItems": 6}, "sample_questions": {**arr, "maxItems": 10}},
        "required": ["product_id", "aliases", "use_cases", "sample_questions"]}}}, "required": ["items"]}


def _describe(p: dict, defs: list[dict]) -> str:
    attrs = "; ".join(f"{a['label']}: {a['display']}" for a in product_attrs(p, defs))
    return (f"[{p['id']}] {p['name']} | hãng {p.get('brand') or '-'} | {p.get('category') or '-'} | "
            f"giá {fmt_price(p.get('price'), p.get('price_unit'))} | {attrs} | {p.get('short_description') or ''}")


async def run_enrich(pool, gem: BaseGemini, demo_id: int, *, overwrite_fields: list[str] | None, product_ids: list[int] | None,
                     timeout_ms: int, per_minute: int, progress=None, batch: int = 5) -> dict:
    overwrite = set(overwrite_fields or [])
    defs = await repo.list_defs(pool, demo_id)
    products = await repo.list_products(pool, demo_id)
    if product_ids:
        products = [p for p in products if p["id"] in set(product_ids)]
    targets = [p for p in products if any(f in overwrite or not p.get(f) for f in FIELDS)]
    limiter = RateLimiter(per_minute)
    proposals: list[dict] = []
    for start in range(0, len(targets), batch):
        chunk = targets[start:start + batch]
        ids = [p["id"] for p in chunk]
        await limiter.acquire(1)
        raw = await gem.generate_json(system=SYSTEM, contents="\n".join(_describe(p, defs) for p in chunk),
                                      schema=_schema(ids), call_type="enrich", timeout_ms=timeout_ms,
                                      demo_id=demo_id, max_output_tokens=4000, temperature=0.4)
        by_id = {p["id"]: p for p in chunk}
        for it in (raw or {}).get("items") or []:
            p = by_id.get(it.get("product_id"))
            if p is None:
                continue
            prop = {"product_id": p["id"], "name": p["name"], "changes": {}}
            for f in FIELDS:
                if f in overwrite or not p.get(f):
                    vals = [v.strip() for v in it.get(f) or [] if isinstance(v, str) and v.strip()]
                    vals = list(dict.fromkeys(vals))
                    if vals:
                        prop["changes"][f] = {"old": p.get(f) or [], "new": vals}
            if prop["changes"]:
                proposals.append(prop)
        if progress:
            await progress(100.0 * min(len(targets), start + batch) / max(1, len(targets)))
    return {"proposals": proposals, "n_targets": len(targets)}


async def apply_enrich(pool, demo_id: int, proposals: list[dict], accept_ids: list[int] | None = None,
                       edits: dict | None = None, mark_reviewed: bool = False) -> dict:
    """edits: {product_id: {field: [..]}} để sửa tay trước khi ghi."""
    accept = set(accept_ids) if accept_ids is not None else {p["product_id"] for p in proposals}
    n = 0
    async with pool.acquire() as conn, conn.transaction():
        for prop in proposals:
            pid = prop["product_id"]
            if pid not in accept:
                continue
            data = {f: c["new"] for f, c in prop["changes"].items()}
            for f, v in ((edits or {}).get(str(pid)) or (edits or {}).get(pid) or {}).items():
                if f in FIELDS:
                    data[f] = v
            data["enrichment_status"] = "reviewed" if mark_reviewed else "ai_draft"
            await repo.patch_product(conn, demo_id, pid, data)
            n += 1
        version = await bump_version(conn, demo_id)
    return {"applied": n, "data_version": version}
