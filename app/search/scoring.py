"""Bước 3-5: điểm tổng hợp, gating rerank, kết hợp rerank, lớp quyết định, câu hỏi làm rõ, lý do."""
from __future__ import annotations

import math

from app.catalog.index import DemoIndex
from app.catalog.texts import attr_display, fmt_price


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-50.0, min(50.0, x))))


def effective_weights(a: dict, has_dense: bool, composite_on: bool = True) -> dict:
    a = dict(a)
    if not composite_on:
        return {"cos": 1.0, "rrf": 0.0, "entity": 0.0, "soft": 0.0, "stock": 0.0, "prev": 0.0}
    if not has_dense:  # mất embedding: dồn trọng số dense sang lexical/entity
        a["rrf"] += a["cos"] * 0.5
        a["entity"] += a["cos"] * 0.5
        a["cos"] = 0.0
    return a


def raw_score(c: dict, a: dict, lo: float, hi: float) -> tuple[float, float]:
    """raw = Σ a_i * tín hiệu_i ; cos chuẩn hoá về 0..1 theo [cos_lo, cos_hi] của demo."""
    cos = c.get("cos")
    cos_n = 0.0 if cos is None else min(1.0, max(0.0, (cos - lo) / max(1e-6, hi - lo)))
    raw = (a["cos"] * cos_n + a["rrf"] * c["rrf"] + a["entity"] * c["entity"] + a["soft"] * c["soft"]
           + a["stock"] * c["stock"] + a["prev"] * c["prev"])
    return raw, cos_n


def composite(idx: DemoIndex, cands: list[dict], *, has_dense: bool, flags: dict) -> None:
    """Gắn raw + final (0..1, đã hiệu chỉnh Platt) cho từng ứng viên."""
    sc, th = idx.scoring, idx.thresholds
    a = effective_weights(sc["a"], has_dense, flags.get("composite", True))
    lo, hi = th.get("cos_lo", sc["cos_lo"]), th.get("cos_hi", sc["cos_hi"])
    for c in cands:
        c["raw"], c["cos_n"] = raw_score(c, a, lo, hi)
        c["final"] = sigmoid(th["platt_a"] * c["raw"] + th["platt_b"])
        c["score"] = c["final"]
    cands.sort(key=lambda c: -c["score"])


def need_rerank(idx: DemoIndex, cands: list[dict], mode: str, exact_unique: int | None, flags: dict) -> tuple[bool, str]:
    if not cands or not flags.get("rerank", True) or mode == "fast":
        return False, "mode_fast" if mode == "fast" else "disabled"
    if mode == "accurate":
        return True, "mode_accurate"
    th = idx.thresholds
    if exact_unique is not None and cands[0]["product_id"] == exact_unique:
        return False, "entity_exact"
    s1 = cands[0]["score"]
    s2 = cands[1]["score"] if len(cands) > 1 else 0.0
    if s1 >= th["gate_high"] and s1 - s2 >= th["gate_margin"]:
        return False, "confident"
    return True, "uncertain"


def apply_rerank(idx: DemoIndex, cands: list[dict], results: dict[int, dict]) -> None:
    sc = idx.scoring
    beta = sc["rerank_beta"]
    top = cands[: sc["rerank_top"]]
    for c in top:
        r = results.get(c["product_id"])
        rel = r["relevance"] if r else sc["rerank_missing_relevance"]
        c["rerank"] = rel
        c["rerank_sat"] = bool(r["satisfies_constraints"]) if r else True
        s = (1 - beta) * c["final"] + beta * rel
        if r and not r["satisfies_constraints"]:
            s *= sc["rerank_violate_penalty"]
        c["score"] = s
        if r and r.get("reason"):
            c["reason"] = r["reason"]
    top.sort(key=lambda c: -c["score"])
    cands[: len(top)] = top


def confidence(score: float, th: dict) -> str:
    return "high" if score >= th["t_match"] else "medium" if score >= th["t_min"] else "low"


def decide(idx: DemoIndex, cands: list[dict], exact_unique: int | None) -> tuple[str, list[dict]]:
    """Trả (status, nhóm sát điểm dùng để hỏi lại)."""
    th = idx.thresholds
    if not cands or cands[0]["score"] < th["t_min"]:
        return "no_match", []
    s1 = cands[0]["score"]
    s2 = cands[1]["score"] if len(cands) > 1 else 0.0
    entity_sure = exact_unique is not None and cands[0]["product_id"] == exact_unique
    if s1 >= th["t_match"] and (s1 - s2 >= th["margin"] or entity_sure):
        return "matched", []
    close = [c for c in cands if c["score"] >= max(th["t_min"], s1 - th["margin_amb"])]
    return "ambiguous", close[:4]


def clarify_question(idx: DemoIndex, close: list[dict]) -> str | None:
    if not close:
        return None
    tpl = (idx.demo.get("settings") or {}).get("clarify_templates") or {}
    prods = [idx.products[c["i"]] for c in close]
    if len(prods) == 1:
        return tpl.get("confirm", "Có phải anh/chị đang hỏi {name} không ạ?").format(name=prods[0]["name"])
    best = None
    for d in idx.defs:
        if d["type"] == "text":
            continue
        vals = []
        for p in prods:
            v = (p.get("attributes") or {}).get(d["key"])
            if d["type"] == "bool" and v is not None:
                disp = f"có {d['label'].lower()}" if v else f"không {d['label'].lower()}"
            else:
                disp = attr_display(d, v)
            if disp and disp not in vals:
                vals.append(disp)
        if len(vals) < 2:
            continue
        # ưu tiên: lọc được > weight cao > ít lựa chọn (dễ hỏi qua thoại)
        key = (bool(d.get("filterable")), float(d.get("weight", 0.5)), -len(vals))
        if best is None or key > best[0]:
            best = (key, d, vals)
    if best is not None:
        _, d, vals = best
        vals = vals[:3]
        opts = " hay ".join(vals) if len(vals) == 2 else ", ".join(vals[:-1]) + " hay " + vals[-1]
        return tpl.get("attr", "Anh/chị muốn loại {options} ạ?").format(options=opts, label=d["label"].lower())
    prices = {p.get("price") for p in prods}
    if len(prices) == len(prods) and None not in prices:
        opts = " hay ".join(f"{p['name']} ({fmt_price(p['price'], p.get('price_unit'))})" for p in prods[:2])
    else:
        opts = " hay ".join(p["name"] for p in prods[:2])
    return tpl.get("name", "Anh/chị đang hỏi {options} ạ?").format(options=opts)


def template_reason(idx: DemoIndex, c: dict, constraints: list) -> str:
    p = idx.products[c["i"]]
    parts = []
    if p.get("brand"):
        parts.append(p["brand"])
    keys = {x.key for x in constraints}
    for a in idx.attrs[c["i"]]:
        if a["key"] in keys:
            if isinstance(a["value"], bool):
                parts.append(a["label"] if a["value"] else f"không {a['label'].lower()}")
            else:
                parts.append(f"{a['label'].lower()} {a['display']}")
    target = next((x.target for x in constraints if x.kind == "price" and x.target), None)
    if p.get("price") is not None:
        s = f"giá {fmt_price(p['price'], p.get('price_unit'))}"
        if target:
            s += f" (khoảng {fmt_price(target, p.get('price_unit'))})"
        parts.append(s)
    if not p.get("in_stock", True):
        parts.append("hiện hết hàng")
    return ", ".join(parts) if parts else p["name"]
