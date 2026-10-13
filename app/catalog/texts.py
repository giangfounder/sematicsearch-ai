"""Sinh văn bản cho vector / BM25 / hiển thị từ sản phẩm + định nghĩa thuộc tính."""
from __future__ import annotations

import hashlib
import re


def fmt_number(v) -> str:
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def fmt_price(v, unit: str | None = None) -> str:
    if v is None:
        return "liên hệ"
    v = float(v)
    if v >= 1e9:
        s = f"{v / 1e9:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " tỷ"
    elif v >= 1e6:
        s = f"{v / 1e6:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " triệu"
    elif v >= 1e3:
        s = f"{v / 1e3:.0f} nghìn"
    else:
        s = fmt_number(v) + " đồng"
    if unit and "/" in unit:
        s += "/" + unit.split("/", 1)[1]
    return s


def attr_display(d: dict, value) -> str:
    if value is None or value == "" or value == []:
        return ""
    t = d.get("type")
    unit = d.get("unit") or ""
    if t == "bool":
        return "Có" if value else "Không"
    if t == "number":
        return f"{fmt_number(value)} {unit}".strip()
    if t == "multi_enum":
        return ", ".join(str(x) for x in value)
    return f"{value} {unit}".strip() if unit and t == "text" else str(value)


def product_attrs(product: dict, defs: list[dict], only_searchable: bool = False) -> list[dict]:
    out = []
    attrs = product.get("attributes") or {}
    for d in defs:
        if only_searchable and not d.get("searchable", True):
            continue
        v = attrs.get(d["key"])
        disp = attr_display(d, v)
        if not disp:
            continue
        out.append({"key": d["key"], "label": d["label"], "value": v, "unit": d.get("unit"), "display": disp})
    return out


def name_text(p: dict) -> str:
    parts = [p["name"]]
    if p.get("brand") and p["brand"].lower() not in p["name"].lower():
        parts.append(p["brand"])
    s = " – ".join(parts)
    if p.get("aliases"):
        s += ". Tên khác: " + ", ".join(p["aliases"])
    return s


def profile_text(p: dict, defs: list[dict]) -> str:
    parts = []
    if p.get("category"):
        parts.append(p["category"])
    if p.get("short_description"):
        parts.append(p["short_description"])
    attrs = product_attrs(p, defs, only_searchable=True)
    if attrs:
        parts.append("; ".join(f"{a['label']}: {a['display']}" for a in attrs))
    if p.get("price") is not None:
        parts.append(f"Giá: {fmt_price(p['price'], p.get('price_unit'))}")
    return ". ".join(parts)


def vector_texts(p: dict, defs: list[dict]) -> list[tuple[str, str]]:
    out = [("name", name_text(p)), ("profile", profile_text(p, defs))]
    out += [("use_case", u) for u in (p.get("use_cases") or []) if u and u.strip()]
    out += [("question", q) for q in (p.get("sample_questions") or []) if q and q.strip()]
    return out


def text_hash(model: str, dim: int, task: str, text: str) -> str:
    return hashlib.sha1(f"{model}|{dim}|{task}|{text}".encode("utf-8")).hexdigest()


_MODEL_RE = re.compile(r"\b(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9-]{3,}\b", re.I)


def model_codes(name: str) -> list[str]:
    """Mã model trong tên (RT22M4032BY, A55, 55U8K...)."""
    return [m.group(0) for m in _MODEL_RE.finditer(name or "")]
