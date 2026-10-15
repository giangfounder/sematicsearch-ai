"""DemoIndex: toàn bộ dữ liệu cần cho search của 1 demo, nằm trong RAM, bất biến sau khi build.
Nạp lại = build bản mới rồi gán tham chiếu (atomic swap), request đang chạy vẫn dùng bản cũ."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from app import repo
from app.catalog.bm25 import BM25
from app.catalog.entity import EntityDict
from app.catalog.quant import dequantize
from app.catalog.texts import fmt_price, name_text, product_attrs, profile_text, text_hash, vector_texts
from app.config import DEFAULT_SCORING, DEFAULT_THRESHOLDS, merged
from app.text.normalize import norm_text, strip_accents, tokens

log = logging.getLogger("index")
KINDS = ["name", "profile", "use_case", "question"]


def bm25_tokens(text: str) -> list[str]:
    s = norm_text(text)
    na = strip_accents(s)
    return tokens(s) + ["~" + t for t in tokens(na)]


@dataclass
class DemoIndex:
    demo: dict
    defs: list[dict]
    products: list[dict]
    version: int
    scoring: dict
    thresholds: dict
    fillers: list[str]
    defs_by_key: dict = field(default_factory=dict)
    pid2i: dict = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    units: set = field(default_factory=set)
    # vectors
    V8: np.ndarray | None = None        # giá trị Int8 (lưu float32 để dùng BLAS)
    Vscale: np.ndarray | None = None
    Vf32: np.ndarray | None = None
    vec_prod: np.ndarray | None = None  # chỉ số sản phẩm của từng vector
    vec_kind: np.ndarray | None = None  # chỉ số kind
    embed_model: str = ""
    # lexical / entity
    bm25_name: BM25 | None = None
    bm25_profile: BM25 | None = None
    entity: EntityDict | None = None
    # hiển thị
    attrs: list[list[dict]] = field(default_factory=list)
    rerank_lines: list[str] = field(default_factory=list)
    prices: np.ndarray | None = None
    in_stock: np.ndarray | None = None
    understand_system: str = ""
    understand_schema: dict = field(default_factory=dict)
    price_unit: str | None = None
    price_median: float | None = None
    built_ms: float = 0.0

    @property
    def slug(self) -> str:
        return self.demo["slug"]

    @property
    def demo_id(self) -> int:
        return self.demo["id"]

    @property
    def n(self) -> int:
        return len(self.products)

    @property
    def n_vectors(self) -> int:
        return 0 if self.V8 is None else self.V8.shape[0]


def build_index(demo: dict, defs: list[dict], products: list[dict], vectors: list[dict]) -> DemoIndex:
    t0 = time.perf_counter()
    settings = demo.get("settings") or {}
    idx = DemoIndex(
        demo=demo, defs=defs, products=products, version=demo["data_version"],
        scoring=merged(DEFAULT_SCORING, settings.get("scoring")),
        thresholds=merged(DEFAULT_THRESHOLDS, demo.get("thresholds")),
        fillers=list(settings.get("fillers") or []),
    )
    idx.defs_by_key = {d["key"]: d for d in defs}
    idx.pid2i = {p["id"]: i for i, p in enumerate(products)}
    idx.categories = sorted({p["category"] for p in products if p.get("category")})
    idx.brands = sorted({p["brand"] for p in products if p.get("brand")})
    for d in defs:
        for u in [d.get("unit"), *(d.get("unit_aliases") or [])]:
            if u:
                idx.units.update(norm_text(u).split()[:1])
    idx.prices = np.array([p["price"] if p.get("price") is not None else np.nan for p in products], dtype=np.float64)
    idx.in_stock = np.array([bool(p.get("in_stock", True)) for p in products])

    # vectors (chỉ của sản phẩm còn tồn tại, cùng embed_model của demo)
    vs = [v for v in vectors if v["product_id"] in idx.pid2i and v["embed_model"] == demo["embed_model"]]
    idx.embed_model = demo["embed_model"]
    if vs:
        dim = len(vs[0]["vec_int8"])
        q = np.frombuffer(b"".join(v["vec_int8"] for v in vs), dtype=np.int8).reshape(len(vs), dim)
        idx.V8 = q.astype(np.float32)
        idx.Vscale = np.array([v["scale"] for v in vs], dtype=np.float32)
        if all(v.get("vec_f32") for v in vs):
            idx.Vf32 = np.frombuffer(b"".join(v["vec_f32"] for v in vs), dtype=np.float32).reshape(len(vs), dim).copy()
        else:
            f = dequantize(q, idx.Vscale)
            idx.Vf32 = f / np.linalg.norm(f, axis=1, keepdims=True)
        idx.vec_prod = np.array([idx.pid2i[v["product_id"]] for v in vs], dtype=np.int32)
        idx.vec_kind = np.array([KINDS.index(v["kind"]) for v in vs], dtype=np.int8)

    # BM25: trường tên (tên + hãng + alias + sku) và trường profile
    idx.bm25_name = BM25([bm25_tokens(f"{name_text(p)} {p['sku']}") for p in products])
    idx.bm25_profile = BM25([bm25_tokens(profile_text(p, defs)) for p in products])
    idx.entity = EntityDict(products, defs)

    for p in products:
        a = product_attrs(p, defs)
        idx.attrs.append(a)
        main = "; ".join(f"{x['label']}: {x['display']}" for x in a[:6])
        uc = ", ".join((p.get("use_cases") or [])[:3])
        line = f"{p['name']} | {fmt_price(p.get('price'), p.get('price_unit'))} | {main}"
        if uc:
            line += f" | Dùng cho: {uc}"
        if not p.get("in_stock", True):
            line += " | HẾT HÀNG"
        idx.rerank_lines.append(line)
    from app.search.prompts import understand_schema, understand_system

    valid = idx.prices[~np.isnan(idx.prices)]
    units = [p.get("price_unit") for p in products if p.get("price_unit")]
    idx.price_unit = max(set(units), key=units.count) if units else None
    idx.price_median = float(np.median(valid)) if len(valid) else None
    prange = (float(valid.min()), float(valid.max())) if len(valid) else None
    idx.understand_system = understand_system(demo, defs, idx.categories, idx.brands, idx.price_unit, prange,
                                              [p["name"] for p in products[:40]])
    idx.understand_schema = understand_schema(defs, idx.categories, idx.brands)
    idx.built_ms = (time.perf_counter() - t0) * 1000
    return idx


async def load_index(db, slug: str) -> DemoIndex | None:
    async with db.acquire() as conn, conn.transaction(isolation="repeatable_read"):
        demo = await repo.get_demo(conn, slug)
        if demo is None:
            return None
        defs = await repo.list_defs(conn, demo["id"])
        products = await repo.list_products(conn, demo["id"])
        vectors = await repo.list_vectors(conn, demo["id"])
    # During re-embedding, old vectors remain durable until final cleanup but
    # must never be used to search the updated product contents.
    valid = {(p["id"], kind, text_hash(demo["embed_model"], demo["embed_dim"], "RETRIEVAL_DOCUMENT", text))
             for p in products for kind, text in vector_texts(p, defs)}
    vectors = [v for v in vectors if (v["product_id"], v["kind"], v["text_hash"]) in valid]
    return await asyncio.to_thread(build_index, demo, defs, products, vectors)


class IndexManager:
    def __init__(self, pool):
        self.pool = pool
        self.indexes: dict[str, DemoIndex] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.on_swap = []  # callback(slug) — ví dụ xoá cache response

    def get(self, slug: str) -> DemoIndex | None:
        return self.indexes.get(slug)

    async def load_all(self) -> None:
        for r in await self.pool.fetch("SELECT slug FROM demos"):
            await self.reload(r["slug"])

    async def reload(self, slug: str, _version: int | None = None) -> DemoIndex | None:
        lock = self._locks.setdefault(slug, asyncio.Lock())
        async with lock:
            cur = self.indexes.get(slug)
            new = await load_index(self.pool, slug)
            if new is None:
                self.indexes.pop(slug, None)
            elif cur is None or new.version >= cur.version or new.demo_id != cur.demo_id:
                self.indexes[slug] = new  # atomic swap
                log.info("index %s v%s: %d sp, %d vector, %.0fms", slug, new.version, new.n, new.n_vectors, new.built_ms)
            for cb in self.on_swap:
                cb(slug)
            return self.indexes.get(slug)

    def drop(self, slug: str) -> None:
        self.indexes.pop(slug, None)

    def versions(self) -> dict[str, int]:
        return {k: v.version for k, v in self.indexes.items()}
