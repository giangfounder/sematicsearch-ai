"""Parser rule-based (luôn chạy, ~1ms): giá, số + đơn vị theo definitions, enum alias, hãng/category
từ entity linking. Là fallback khi Gemini lỗi và là nguồn "thắng" khi mâu thuẫn ở giá/số."""
from __future__ import annotations

import re

from app.catalog.entity import EntityResult
from app.text.normalize import norm_text, strip_accents
from app.text.vn_numbers import BASE_UNITS, spoken_to_digits

NUM = r"(\d+(?:[.,]\d+)?)"
MONEY_UNITS = {"tỷ": 1e9, "tỉ": 1e9, "triệu": 1e6, "tr": 1e6, "củ": 1e6, "chai": 1e6,
               "nghìn": 1e3, "ngàn": 1e3, "k": 1e3, "đồng": 1.0, "vnd": 1.0, "đ": 1.0}
_MONEY_RE = re.compile(
    NUM + r"(?:-" + NUM + r")?\s*(tỷ|tỉ|triệu|tr|củ|chai|nghìn|ngàn|k|đồng|vnd|đ)\b"
    r"(?:\s*(rưỡi|\d{1,3})(?!\s*(?:nghìn|ngàn|k|lít|inch|in|gb|cửa|m2)\b))?")
_RANGE_RE = re.compile(
    r"(?:từ\s+)?" + NUM + r"\s*(tỷ|tỉ|triệu|tr|củ|nghìn|ngàn|k)?\s*(?:đến|tới|-)\s*" + NUM
    + r"\s*(tỷ|tỉ|triệu|tr|củ|chai|nghìn|ngàn|k|đồng|vnd|đ)\b")
_BIG_NUM_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d{3}){2,})\b")
LT_WORDS = ("dưới", "không quá", "tối đa", "nhỏ hơn", "ít hơn", "thấp hơn", "chưa tới", "chưa đến", "đổ lại", "trở xuống", "max")
GT_WORDS = ("trên", "hơn", "ít nhất", "tối thiểu", "lớn hơn", "cao hơn", "trở lên", "từ", "min")
APPROX_WORDS = ("tầm", "khoảng", "cỡ", "chừng", "xấp xỉ", "quanh", "loanh quanh", "tầm tầm", "khoảng chừng", "độ")
CHEAP_SUPER = ("rẻ nhất", "giá thấp nhất", "thấp nhất", "rẻ hết")
EXP_SUPER = ("đắt nhất", "cao cấp nhất", "xịn nhất", "giá cao nhất", "mắc nhất")
CHEAP_SOFT = ("giá rẻ", "rẻ rẻ", "bình dân", "tiết kiệm chi phí", "sinh viên", "rẻ")


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def _context_op(before: str, after: str) -> str:
    b = before[-20:]
    a = after[:15]
    if "trở xuống" in a or "đổ lại" in a or "đổ xuống" in a:
        return "lte"
    if "trở lên" in a or "đổ lên" in a:
        return "gte"
    for w in APPROX_WORDS:
        if re.search(r"(?:^|\s)" + w + r"\s*$", b):
            return "approx"
    for w in LT_WORDS:
        if re.search(r"(?:^|\s)" + w + r"\s*$", b):
            return "lte"
    for w in GT_WORDS:
        if re.search(r"(?:^|\s)" + w + r"\s*$", b):
            return "gte"
    return "approx"


def parse_money(text: str, units: set[str] | None = None) -> dict | None:
    """Trả {min,max,approx,sort,explicit} theo VND hoặc None.
    units: đơn vị thuộc tính của demo, để "7 triệu 2 cánh" không thành 7,2 triệu."""
    block = BASE_UNITS | (units or set())
    price: dict = {}
    rm = _RANGE_RE.search(text)
    if rm:
        hi_mult = MONEY_UNITS[rm.group(4)]
        lo_mult = MONEY_UNITS[rm.group(2)] if rm.group(2) else hi_mult
        lo, hi = sorted([_f(rm.group(1)) * lo_mult, _f(rm.group(3)) * hi_mult])
        price.update(min=lo, max=hi, explicit=True)
    matches = [] if rm else list(_MONEY_RE.finditer(text))
    vals: list[tuple[float, float | None, int, int]] = []
    for m in matches:
        mult = MONEY_UNITS[m.group(3)]
        v1 = _f(m.group(1)) * mult
        v2 = _f(m.group(2)) * mult if m.group(2) else None
        tail = m.group(4)
        nxt = text[m.end():].split(" ", 2)
        if tail and tail != "rưỡi" and len(nxt) > 1 and nxt[1] in block:
            tail = None
        if tail == "rưỡi":
            v1 += 0.5 * mult
        elif tail and mult >= 1e6:
            v1 += float(tail) / (10 ** len(tail)) * mult
        vals.append((v1, v2, m.start(), m.end()))
    for m in ([] if rm else _BIG_NUM_RE.finditer(text)):
        vals.append((float(re.sub(r"[.,]", "", m.group(1))), None, m.start(), m.end()))
    vals.sort(key=lambda x: x[2])
    if vals:
        # "từ A đến/tới B"
        if len(vals) >= 2:
            mid = text[vals[0][3]:vals[1][2]]
            if re.search(r"\b(đến|tới|-)\b", mid) or mid.strip() in ("-", "đến", "tới"):
                lo, hi = sorted([vals[0][0], vals[1][0]])
                price.update(min=lo, max=hi)
        if not price:
            v1, v2, s, e = vals[0]
            if v2 is not None:
                price.update(min=min(v1, v2), max=max(v1, v2))
            else:
                op = _context_op(text[:s], text[e:])
                if op == "lte":
                    price["max"] = v1
                elif op == "gte":
                    price["min"] = v1
                else:
                    price["approx"] = v1
        price["explicit"] = True
    if any(w in text for w in CHEAP_SUPER):
        price["sort"] = "asc"
        price.setdefault("explicit", True)
    elif any(w in text for w in EXP_SUPER):
        price["sort"] = "desc"
        price.setdefault("explicit", True)
    elif any(re.search(r"(?:^|\s)" + w + r"(?:\s|$)", text) for w in CHEAP_SOFT) and "sort" not in price:
        price["sort"] = "asc"
        price.setdefault("explicit", False)
    return price or None


def _unit_regex(d: dict) -> re.Pattern | None:
    units = [d.get("unit"), *(d.get("unit_aliases") or [])]
    units = sorted({norm_text(u) for u in units if u}, key=len, reverse=True)
    if not units:
        return None
    alt = "|".join(re.escape(u) for u in units)
    return re.compile(NUM + r"(?:-" + NUM + r")?\s*(?:" + alt + r")(?=\s|$)")


def parse_attributes(text: str, defs: list[dict], ent: EntityResult | None) -> list[dict]:
    out: list[dict] = []
    for d in defs:
        if d["type"] == "number":
            rx = _unit_regex(d)
            if rx is None:
                continue
            m = rx.search(text)
            if not m:
                continue
            v1 = _f(m.group(1))
            if m.group(2):
                out.append({"key": d["key"], "op": "between", "value": min(v1, _f(m.group(2))),
                            "value_max": max(v1, _f(m.group(2))), "explicit": True, "source": "rule"})
                continue
            op = _context_op(text[:m.start()], text[m.end():])
            before = text[:m.start()][-12:]
            if op == "approx" and not any(re.search(r"(?:^|\s)" + w + r"\s*$", before) for w in APPROX_WORDS):
                op = "eq"
            out.append({"key": d["key"], "op": op, "value": v1, "explicit": True, "source": "rule"})
        elif d["type"] == "bool":
            labels = [d["label"], *(d.get("label_aliases") or [])]
            na = strip_accents(text)
            for lb in labels:
                k = strip_accents(norm_text(lb))
                if k and re.search(r"(?:^|\s)" + re.escape(k) + r"(?:\s|$)", na):
                    neg = re.search(r"(?:không|ko|khong)\s+(?:co\s+)?" + re.escape(k), na)
                    out.append({"key": d["key"], "op": "eq", "value": not bool(neg), "explicit": False, "source": "rule"})
                    break
    if ent:
        defs_by_key = {d["key"]: d for d in defs}
        for h in ent.enum_hits:
            d = defs_by_key.get(h["key"])
            if d and not any(a["key"] == h["key"] for a in out):
                out.append({"key": h["key"], "op": "eq", "value": h["value"], "explicit": True, "source": "rule"})
    return out


def parse_rules(text_norm: str, defs: list[dict], ent: EntityResult | None, units: set[str] | None = None) -> dict:
    """text_norm: câu đã chuẩn hoá (có dấu). Trả filters chuẩn nội bộ."""
    t = spoken_to_digits(text_norm, units)
    filters: dict = {"price": parse_money(t, units), "category": None, "brand": None, "in_stock": None,
                     "attributes": parse_attributes(t, defs, ent), "category_explicit": False, "brand_explicit": False}
    if ent:
        if ent.brands:
            filters["brand"], filters["brand_explicit"] = ent.brands[0], True
        if ent.categories:
            filters["category"], filters["category_explicit"] = ent.categories[0], True
    if re.search(r"(?:^|\s)còn hàng(?:\s|$)", t):
        filters["in_stock"] = True
    filters["_digits_text"] = t
    return filters
