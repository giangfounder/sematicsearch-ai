"""Entity linking cục bộ: khớp n-gram của câu với từ điển thực thể của demo
(tên, alias, SKU, mã model, hãng, category, giá trị enum) ở dạng không dấu; exact trước, fuzzy sau."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.catalog.texts import model_codes
from app.text.normalize import norm_text, strip_accents

MAX_N = 7


def _key(s: str) -> str:
    return strip_accents(norm_text(s))


def _trigrams(s: str) -> set[str]:
    p = f" {s} "
    return {p[i:i + 3] for i in range(len(p) - 2)}


@dataclass
class Entry:
    etype: str        # product | brand | category | enum
    target: object    # pid | brand | category | (key, value)
    strength: float
    surface: str


@dataclass
class EntityResult:
    products: dict[int, dict] = field(default_factory=dict)   # pid -> {score, match, surface}
    brands: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    enum_hits: list[dict] = field(default_factory=list)       # {key, value, surface}

    @property
    def exact_unique(self) -> int | None:
        exact = [pid for pid, h in self.products.items() if h["match"] == "exact" and h["score"] >= 0.9]
        return exact[0] if len(exact) == 1 else None

    def to_dict(self) -> dict:
        return {"products": [{"product_id": k, **v} for k, v in
                             sorted(self.products.items(), key=lambda kv: -kv[1]["score"])],
                "brands": self.brands, "categories": self.categories, "enum_hits": self.enum_hits}


class EntityDict:
    def __init__(self, products: list[dict], defs: list[dict], fuzzy_min_ratio: float = 85.0):
        self.fuzzy_min = fuzzy_min_ratio
        self.exact: dict[str, list[Entry]] = defaultdict(list)
        brands = {p["brand"] for p in products if p.get("brand")}
        cats = {p["category"] for p in products if p.get("category")}
        generic = {_key(x) for x in brands | cats}
        for b in brands:
            self._add(b, Entry("brand", b, 1.0, b))
        for c in cats:
            self._add(c, Entry("category", c, 1.0, c))
        for d in defs:
            if d["type"] not in ("enum", "multi_enum"):
                continue
            for ev in d.get("enum_values") or []:
                val = ev["value"] if isinstance(ev, dict) else ev
                als = ev.get("aliases", []) if isinstance(ev, dict) else []
                for s in [val, *als]:
                    k = _key(str(s))
                    if k and not k.replace(" ", "").isdigit():
                        self._add(str(s), Entry("enum", (d["key"], val), 1.0, str(s)))
        for p in products:
            pid = p["id"]
            surfaces: list[tuple[str, float]] = [(p["name"], 1.0), (p["sku"], 1.0)]
            surfaces += [(a, 1.0) for a in p.get("aliases") or []]
            surfaces += [(m, 0.95) for m in model_codes(p["name"])]
            cat = p.get("category")
            if cat and _key(p["name"]).startswith(_key(cat) + " "):
                surfaces.append((p["name"][len(cat):].strip(), 0.95))
            seen = set()
            for s, st in surfaces:
                k = _key(s)
                if not k or k in seen or k in generic or len(k) < 3:
                    continue
                seen.add(k)
                self._add(s, Entry("product", pid, st, s))
        # index trigram cho fuzzy (chỉ product + brand)
        self.tri: dict[str, set[str]] = defaultdict(set)
        self.tri_size: dict[str, int] = {}
        for k, entries in self.exact.items():
            if len(k) >= 4 and any(e.etype in ("product", "brand") for e in entries):
                tg = _trigrams(k)
                self.tri_size[k] = len(tg)
                for t in tg:
                    self.tri[t].add(k)

    def _add(self, surface: str, e: Entry) -> None:
        k = _key(surface)
        if k and not any(x.etype == e.etype and x.target == e.target for x in self.exact[k]):
            self.exact[k].append(e)

    def _fuzzy(self, gram: str) -> list[tuple[str, float]]:
        tg = _trigrams(gram)
        counts: dict[str, int] = defaultdict(int)
        for t in tg:
            for k in self.tri.get(t, ()):
                counts[k] += 1
        out = []
        for k, inter in counts.items():
            jac = inter / (len(tg) + self.tri_size[k] - inter)
            if jac < 0.45:
                continue
            r = fuzz.ratio(gram, k)
            if r >= self.fuzzy_min:
                out.append((k, r / 100.0))
        return out

    def match(self, text_noacc: str, fuzzy: bool = True) -> EntityResult:
        syl = text_noacc.split()
        res = EntityResult()
        hits: list[tuple[int, int, str, float, str]] = []  # (start, end, key, score, match)
        for n in range(min(MAX_N, len(syl)), 0, -1):
            for i in range(len(syl) - n + 1):
                g = " ".join(syl[i:i + n])
                if g in self.exact:
                    hits.append((i, i + n, g, 1.0, "exact"))
                elif fuzzy and len(g) >= 5 and n >= 1:
                    for k, sc in self._fuzzy(g):
                        hits.append((i, i + n, k, sc, "fuzzy"))
        # tham lam: exact trước fuzzy, rồi span dài & điểm cao; mỗi loại thực thể không chồng lấn span trong cùng loại
        hits.sort(key=lambda h: (h[4] != "exact", -(h[1] - h[0]), -h[3]))
        used: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for s, e, k, sc, how in hits:
            entries = self.exact[k]
            for etype in {x.etype for x in entries}:
                if any(not (e <= a or s >= b) for a, b in used[etype]):
                    continue
                used[etype].append((s, e))
                group = [x for x in entries if x.etype == etype]
                for x in group:
                    score = x.strength * sc * (1.0 if len(group) == 1 else 0.6)
                    if etype == "product":
                        cur = res.products.get(x.target)
                        if cur is None or score > cur["score"]:
                            res.products[x.target] = {"score": round(score, 4), "match": how if len(group) == 1 else f"{how}_shared",
                                                      "surface": x.surface}
                    elif etype == "brand" and x.target not in res.brands:
                        res.brands.append(x.target)
                    elif etype == "category" and x.target not in res.categories:
                        res.categories.append(x.target)
                    elif etype == "enum" and how == "exact":
                        key, val = x.target
                        if not any(h["key"] == key and h["value"] == val for h in res.enum_hits):
                            res.enum_hits.append({"key": key, "value": val, "surface": x.surface})
        return res
