"""Hiểu câu: gọi Gemini (structured output), validate theo definitions, hợp nhất với rule parser."""
from __future__ import annotations

import math

import numpy as np

from app.catalog.index import DemoIndex
from app.search.prompts import INTENTS, understand_contents
from app.text.normalize import norm_text, strip_accents

OPS = {"eq", "gte", "lte", "between", "approx"}


def _canon(values: list[str], v) -> str | None:
    if not isinstance(v, str) or not v.strip():
        return None
    k = strip_accents(norm_text(v))
    for x in values:
        if strip_accents(norm_text(x)) == k:
            return x
    return None


def _enum_value(d: dict, v) -> str | None:
    if v is None:
        return None
    k = strip_accents(norm_text(str(v)))
    for ev in d.get("enum_values") or []:
        val = ev["value"] if isinstance(ev, dict) else ev
        als = ev.get("aliases", []) if isinstance(ev, dict) else []
        if any(strip_accents(norm_text(str(x))) == k for x in [val, *als]):
            return val
    return None


def _to_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        k = strip_accents(norm_text(v))
        if k in ("true", "co", "yes", "1", "dung"):
            return True
        if k in ("false", "khong", "no", "0", "sai"):
            return False
    return None


def scale_price(v, idx: DemoIndex) -> float | None:
    """Đưa số giá về VND: chọn hệ số 1/1e3/1e6/1e9 gần trung vị giá catalog nhất (log)."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v <= 0 or math.isnan(v):
        return None
    med = idx.price_median
    if not med or v >= med / 50:
        return v
    best = min((1.0, 1e3, 1e6, 1e9), key=lambda m: abs(math.log10(v * m) - math.log10(med)))
    return v * best


def plausible_price(v: float | None, idx: DemoIndex) -> bool:
    if v is None:
        return True
    valid = idx.prices[~np.isnan(idx.prices)]
    if not len(valid):
        return True
    return valid.min() / 20 <= v <= valid.max() * 20


def validate_llm(raw: dict, idx: DemoIndex) -> dict:
    """Lọc output LLM theo definitions: bỏ key lạ, sai kiểu, enum ngoài danh sách."""
    out: dict = {"intent": "find_product", "rewritten_query": "", "mentioned_products": [], "dropped": []}
    if not isinstance(raw, dict):
        return out
    if raw.get("intent") in INTENTS:
        out["intent"] = raw["intent"]
    rq = raw.get("rewritten_query")
    out["rewritten_query"] = rq.strip() if isinstance(rq, str) else ""
    mp = raw.get("mentioned_products")
    out["mentioned_products"] = [x for x in mp if isinstance(x, str)][:5] if isinstance(mp, list) else []
    f = raw.get("filters") if isinstance(raw.get("filters"), dict) else {}
    filters: dict = {"price": None, "category": None, "brand": None, "in_stock": None, "attributes": []}
    p = f.get("price")
    if isinstance(p, dict):
        price = {}
        for k in ("min", "max", "approx"):
            v = scale_price(p.get(k), idx)
            if v is not None and plausible_price(v, idx):
                price[k] = v
        if p.get("sort") in ("asc", "desc"):
            price["sort"] = p["sort"]
        if price:
            price["explicit"] = bool(p.get("explicit", True))
            filters["price"] = price
    cat = _canon(idx.categories, f.get("category"))
    if f.get("category") and cat is None:
        out["dropped"].append(f"category:{f.get('category')}")
    filters["category"] = cat
    br = _canon(idx.brands, f.get("brand"))
    if f.get("brand") and br is None:
        out["dropped"].append(f"brand:{f.get('brand')}")
    filters["brand"] = br
    if isinstance(f.get("in_stock"), bool):
        filters["in_stock"] = f["in_stock"]
    for a in f.get("attributes") or []:
        if not isinstance(a, dict):
            continue
        d = idx.defs_by_key.get(a.get("key"))
        op = a.get("op") if a.get("op") in OPS else "eq"
        if d is None:
            out["dropped"].append(f"attr:{a.get('key')}")
            continue
        item = {"key": d["key"], "op": op, "explicit": bool(a.get("explicit")) and bool(d.get("filterable")),
                "source": "llm"}
        t = d["type"]
        if t == "number":
            v = a.get("value_num")
            if not isinstance(v, (int, float)):
                try:
                    v = float(str(a.get("value_text")).replace(",", "."))
                except (TypeError, ValueError):
                    out["dropped"].append(f"attr:{d['key']}:type")
                    continue
            item["value"] = float(v)
            if op == "between":
                vm = a.get("value_num_max")
                if not isinstance(vm, (int, float)):
                    item["op"] = "gte"
                else:
                    item["value_max"] = float(vm)
        elif t in ("enum", "multi_enum"):
            v = _enum_value(d, a.get("value_text"))
            if v is None:
                out["dropped"].append(f"attr:{d['key']}:enum")
                continue
            item["value"], item["op"] = v, "eq"
        elif t == "bool":
            v = _to_bool(a.get("value_text") if a.get("value_text") is not None else a.get("value_num"))
            if v is None:
                out["dropped"].append(f"attr:{d['key']}:bool")
                continue
            item["value"], item["op"] = v, "eq"
        else:  # text: không lọc, chỉ dùng như mong muốn mềm khớp chuỗi
            v = a.get("value_text")
            if not isinstance(v, str) or not v.strip():
                continue
            item["value"], item["op"], item["explicit"] = v, "eq", False
        filters["attributes"].append(item)
    out["filters"] = filters
    return out


def merge_filters(llm: dict | None, rules: dict, ent_brands: list[str], ent_cats: list[str], idx: DemoIndex) -> dict:
    """Rule thắng ở giá và thuộc tính số; còn lại hợp nhất. Hãng/category chỉ explicit khi khách nói ra
    (có trong entity linking); nếu chỉ do LLM suy ra thì là ràng buộc mềm."""
    out = {"price": None, "category": None, "brand": None, "in_stock": None, "attributes": [],
           "category_explicit": False, "brand_explicit": False}
    lf = (llm or {}).get("filters") or {}
    rp = dict(rules.get("price") or {})
    for k in ("min", "max", "approx"):
        if k in rp and not plausible_price(rp[k], idx):
            rp.pop(k)
    lp = lf.get("price") or {}
    has_num = lambda p: any(k in p for k in ("min", "max", "approx"))  # noqa: E731
    if has_num(rp):
        price = rp
        if "sort" not in price and lp.get("sort"):
            price["sort"] = lp["sort"]
    elif lp:
        price = dict(lp)
        if rp.get("sort"):
            price["sort"] = rp["sort"]
    else:
        price = rp if rp.get("sort") else None
    out["price"] = price or None
    for key in ("category", "brand"):
        rv, lv = rules.get(key), lf.get(key)
        if rv:
            out[key], out[f"{key}_explicit"] = rv, True
        elif lv:
            said = ent_brands if key == "brand" else ent_cats
            out[key], out[f"{key}_explicit"] = lv, lv in said
    out["in_stock"] = rules.get("in_stock") if rules.get("in_stock") is not None else lf.get("in_stock")
    attrs = {a["key"]: a for a in lf.get("attributes") or []}
    for a in rules.get("attributes") or []:
        d = idx.defs_by_key.get(a["key"])
        if a["key"] not in attrs or (d and d["type"] == "number"):
            a = dict(a)
            a["explicit"] = a["explicit"] and bool(d and d.get("filterable"))
            attrs[a["key"]] = a
    out["attributes"] = list(attrs.values())
    return out


def build_llm_request(idx: DemoIndex, text: str, ctx: dict | None, candidate_names: list[str]) -> tuple[str, str, dict]:
    prev_names = []
    for pid in (ctx or {}).get("previous_product_ids") or []:
        i = idx.pid2i.get(pid)
        if i is not None:
            prev_names.append(idx.products[i]["name"])
    return idx.understand_system, understand_contents(text, ctx, prev_names, candidate_names), idx.understand_schema
