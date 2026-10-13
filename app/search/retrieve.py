"""Truy xuất lai trên RAM: lọc cứng (chỉ ràng buộc explicit + filterable) có nới dần, dense Int8 đa vector,
BM25 có dấu/không dấu, entity, hợp nhất RRF, chấm lại cosine float32, điểm thoả ràng buộc mềm."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.catalog.index import KINDS, DemoIndex, bm25_tokens
from app.catalog.quant import int8_cosine, quantize
from app.text.normalize import norm_text, strip_accents

_TOL_EQ = 0.05


@dataclass
class Constraint:
    key: str
    kind: str              # price | brand | category | in_stock | attr | previous
    explicit: bool
    weight: float
    desc: str
    hard: object = None    # fn(i) -> bool | None (None = không lọc cứng được)
    sat: object = None     # fn(i) -> float 0..1
    sort: str | None = None
    target: float | None = None


@dataclass
class Retrieval:
    candidates: list[dict]
    constraints: list[Constraint]
    relaxed_keys: list[str] = field(default_factory=list)
    n_allowed: int = 0


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _range_fns(op: str, v: float, vmax: float | None, band: float):
    def hard(x):
        if x is None:
            return False
        if op == "lte":
            return x <= v
        if op == "gte":
            return x >= v
        if op == "between":
            return v <= x <= (vmax if vmax is not None else v)
        if op == "approx":
            return abs(x - v) <= band * abs(v)
        return abs(x - v) <= max(_TOL_EQ * abs(v), 0.5 if abs(v) < 20 else 0)  # eq

    def sat(x):
        if x is None:
            return 0.3
        if op == "lte":
            return 1.0 if x <= v else max(0.0, 1 - (x - v) / (0.3 * v or 1))
        if op == "gte":
            return 1.0 if x >= v else max(0.0, 1 - (v - x) / (0.3 * v or 1))
        if op == "between":
            hi = vmax if vmax is not None else v
            if v <= x <= hi:
                return 1.0
            d = (v - x) if x < v else (x - hi)
            return max(0.0, 1 - d / (0.3 * (hi or 1)))
        width = (2 * band if op == "approx" else 0.5) * (abs(v) or 1)
        return max(0.0, 1 - abs(x - v) / width)

    return hard, sat


def _eq_str(a, b) -> bool:
    return strip_accents(norm_text(str(a))) == strip_accents(norm_text(str(b)))


def build_constraints(idx: DemoIndex, filters: dict, intent: str, ctx: dict | None, ent_products: dict,
                      soft_filter: bool = True) -> list[Constraint]:
    sc = idx.scoring
    band = sc["approx_band"]
    P = idx.products
    out: list[Constraint] = []
    price = filters.get("price") or {}
    pw = float(sc.get("price_weight", 0.9))
    prices = [_num(p.get("price")) for p in P]
    for op, k in (("lte", "max"), ("gte", "min"), ("approx", "approx")):
        if price.get(k) is not None:
            h, s = _range_fns(op, float(price[k]), None, band)
            out.append(Constraint("price", "price", bool(price.get("explicit", True)), pw, f"giá {op} {price[k]:,.0f}",
                                  hard=lambda i, h=h: h(prices[i]), sat=lambda i, s=s: s(prices[i]),
                                  target=float(price[k]) if op == "approx" else None))
    if price.get("sort"):
        out.append(Constraint("price_sort", "price", False, 0.5, f"giá sort {price['sort']}", sort=price["sort"]))
    for key, w in (("category", 0.95), ("brand", 0.85)):
        val = filters.get(key)
        if val:
            out.append(Constraint(key, key, bool(filters.get(f"{key}_explicit")), float(sc.get(f"{key}_weight", w)),
                                  f"{key} = {val}", hard=lambda i, key=key, val=val: _eq_str(P[i].get(key) or "", val),
                                  sat=lambda i, key=key, val=val: float(_eq_str(P[i].get(key) or "", val))))
    if filters.get("in_stock") is True:
        out.append(Constraint("in_stock", "in_stock", True, 0.3, "còn hàng",
                              hard=lambda i: bool(P[i].get("in_stock", True)),
                              sat=lambda i: float(bool(P[i].get("in_stock", True)))))
    for a in filters.get("attributes") or []:
        d = idx.defs_by_key.get(a["key"])
        if d is None:
            continue
        key, t, v = d["key"], d["type"], a.get("value")
        vals = [(p.get("attributes") or {}).get(key) for p in P]
        w = float(d.get("weight", 0.5))
        explicit = bool(a.get("explicit")) and bool(d.get("filterable"))
        desc = f"{d['label']} {a.get('op', 'eq')} {v}" + (f"-{a['value_max']}" if a.get("value_max") is not None else "")
        if t == "number":
            h, s = _range_fns(a.get("op", "eq"), float(v), a.get("value_max"), band)
            out.append(Constraint(key, "attr", explicit, w, desc, hard=lambda i, h=h, vals=vals: h(_num(vals[i])),
                                  sat=lambda i, s=s, vals=vals: s(_num(vals[i]))))
        elif t in ("enum", "multi_enum"):
            def m(i, vals=vals, v=v, t=t):
                x = vals[i]
                if x is None:
                    return False
                return any(_eq_str(y, v) for y in x) if t == "multi_enum" and isinstance(x, list) else _eq_str(x, v)
            out.append(Constraint(key, "attr", explicit, w, desc, hard=m, sat=lambda i, m=m: float(m(i))))
        elif t == "bool":
            def mb(i, vals=vals, v=v):
                return vals[i] is not None and bool(vals[i]) == bool(v)
            out.append(Constraint(key, "attr", explicit, w, desc, hard=mb, sat=lambda i, mb=mb: float(mb(i))))
        else:
            needle = strip_accents(norm_text(str(v)))
            out.append(Constraint(key, "attr", False, w, desc,
                                  sat=lambda i, vals=vals, needle=needle: float(needle in strip_accents(norm_text(str(vals[i] or ""))))))
    prev = [pid for pid in (ctx or {}).get("previous_product_ids") or [] if pid in idx.pid2i]
    if prev and intent == "ask_detail" and not ent_products:
        prev_set = {idx.pid2i[p] for p in prev}
        out.append(Constraint("previous", "previous", True, 1.0, "sản phẩm lượt trước",
                              hard=lambda i: i in prev_set, sat=lambda i: float(i in prev_set)))
    if not soft_filter:  # baseline: mọi ràng buộc LLM trả về đều lọc cứng
        for c in out:
            if c.hard is not None:
                c.explicit = True
    return out


def apply_hard(idx: DemoIndex, constraints: list[Constraint], relax: bool = True) -> tuple[np.ndarray, list[str]]:
    active = [c for c in constraints if c.explicit and c.hard is not None]
    relaxed: list[str] = []
    while True:
        mask = np.ones(idx.n, dtype=bool)
        for c in active:
            mask &= np.fromiter((c.hard(i) for i in range(idx.n)), dtype=bool, count=idx.n)
        if mask.any() or not active or not relax:
            break
        # nới ràng buộc có weight thấp nhất (giữ thứ tự ổn định)
        drop = min(range(len(active)), key=lambda j: (active[j].weight, -j))
        relaxed.append(active[drop].key)
        active.pop(drop)
    return mask, relaxed


def dense_scores(idx: DemoIndex, qvec: np.ndarray, use_int8: bool, kinds_allowed: set[int]) -> tuple[np.ndarray, np.ndarray]:
    """Trả (điểm sản phẩm = max_kind(w_kind * cos), ma trận n x 4 cos thô theo kind)."""
    n = idx.n
    best = np.full(n, -np.inf, dtype=np.float32)
    per_kind = np.full((n, len(KINDS)), -np.inf, dtype=np.float32)
    if idx.V8 is None or qvec is None:
        return best, per_kind
    if use_int8:
        q8, qs = quantize(qvec[None, :])
        cos = int8_cosine(q8[0], float(qs[0]), idx.V8, idx.Vscale)
    else:
        cos = idx.Vf32 @ qvec
    sel = np.isin(idx.vec_kind, list(kinds_allowed))
    kw = np.array([idx.scoring["kind_weights"].get(k, 1.0) for k in KINDS], dtype=np.float32)
    w = cos * kw[idx.vec_kind]
    np.maximum.at(best, idx.vec_prod[sel], w[sel])
    np.maximum.at(per_kind, (idx.vec_prod[sel], idx.vec_kind[sel]), cos[sel])
    return best, per_kind


def bm25_scores(idx: DemoIndex, texts: list[str]) -> np.ndarray:
    fw = idx.scoring["bm25_field_weights"]
    out = np.zeros(idx.n, dtype=np.float32)
    for t in texts:
        if not t:
            continue
        toks = bm25_tokens(t)
        s = fw["name"] * idx.bm25_name.scores(toks) + fw["profile"] * idx.bm25_profile.scores(toks)
        out = np.maximum(out, s)
    return out


def _ranks(scores: np.ndarray, allowed: np.ndarray, positive_only: bool) -> dict[int, int]:
    ids = np.where(allowed & np.isfinite(scores) & ((scores > 0) if positive_only else True))[0]
    order = ids[np.argsort(-scores[ids], kind="stable")]
    return {int(i): r + 1 for r, i in enumerate(order)}


def retrieve(idx: DemoIndex, *, qvec: np.ndarray | None, texts: list[str], filters: dict, intent: str,
             ctx: dict | None, ent_products: dict, flags: dict) -> Retrieval:
    sc = idx.scoring
    constraints = build_constraints(idx, filters, intent, ctx, ent_products, soft_filter=flags.get("soft_filter", True))
    allowed, relaxed = apply_hard(idx, constraints, relax=flags.get("relax", True))
    kinds_allowed = set(range(len(KINDS))) if flags.get("multi_vector", True) else {KINDS.index("profile")}
    dense, per_kind = dense_scores(idx, qvec, True, kinds_allowed)
    bm = bm25_scores(idx, texts) if flags.get("bm25", True) else np.zeros(idx.n, np.float32)
    ent = np.zeros(idx.n, np.float32)
    if flags.get("entity", True):
        for pid, h in ent_products.items():
            i = idx.pid2i.get(pid)
            if i is not None:
                ent[i] = h["score"]
    k, w = sc["rrf_k"], sc["rrf_weights"]
    signals = {"dense": (dense, False), "bm25": (bm, True), "entity": (ent, True)}
    if not flags.get("bm25", True):
        signals.pop("bm25")
    if not flags.get("entity", True):
        signals.pop("entity")
    ranks = {name: _ranks(s, allowed, pos) for name, (s, pos) in signals.items()}
    rrf = np.zeros(idx.n, dtype=np.float32)
    for name, rk in ranks.items():
        for i, r in rk.items():
            rrf[i] += w.get(name, 1.0) / (k + r)
    # chỉ chuẩn hoá theo tín hiệu thực sự có mặt (mất embedding thì dense không được tính vào mẫu số)
    rrf_max = sum(w.get(name, 1.0) / (k + 1) for name, rk in ranks.items() if rk) or 1.0
    pool_ids = np.where(allowed & (rrf > 0))[0]
    if flags.get("baseline"):
        pool_ids = np.where(allowed & np.isfinite(dense))[0]
        pool_ids = pool_ids[np.argsort(-dense[pool_ids], kind="stable")][: sc["retrieve_top"]]
    else:
        pool_ids = pool_ids[np.argsort(-rrf[pool_ids], kind="stable")][: sc["retrieve_top"]]

    # chấm lại cosine float32 cho top ứng viên
    if flags.get("float_rescore", True) and qvec is not None and idx.Vf32 is not None:
        f32_best, _ = dense_scores(idx, qvec, False, kinds_allowed)
    else:
        f32_best = dense

    # điểm mềm
    sort_c = [c for c in constraints if c.sort]
    sort_rank: dict[int, float] = {}
    if sort_c and len(pool_ids):
        pr = np.array([idx.prices[i] if not np.isnan(idx.prices[i]) else np.inf for i in pool_ids])
        order = np.argsort(pr if sort_c[0].sort == "asc" else -pr, kind="stable")
        for r, j in enumerate(order):
            sort_rank[int(pool_ids[j])] = 1 - r / max(1, len(pool_ids) - 1)
    prev = set((ctx or {}).get("previous_product_ids") or [])
    cands = []
    for i in pool_ids:
        i = int(i)
        num = den = 0.0
        for c in constraints:
            s = sort_rank.get(i, 0.5) if c.sort else float(c.sat(i))
            num += c.weight * s
            den += c.weight
        cands.append({
            "i": i, "product_id": idx.products[i]["id"],
            "dense": float(dense[i]) if np.isfinite(dense[i]) else None,
            "dense_kinds": {KINDS[k2]: round(float(per_kind[i, k2]), 4) for k2 in range(len(KINDS)) if np.isfinite(per_kind[i, k2])},
            "cos": float(f32_best[i]) if np.isfinite(f32_best[i]) else None,
            "bm25": float(bm[i]), "entity": float(ent[i]),
            "rrf": float(rrf[i]) / rrf_max,
            "soft": num / den if den else 1.0,
            "stock": 1.0 if idx.in_stock[i] else 0.0,
            "prev": 1.0 if idx.products[i]["id"] in prev and intent in ("refine_previous", "ask_detail") else 0.0,
        })
    return Retrieval(cands, constraints, relaxed, int(allowed.sum()))
