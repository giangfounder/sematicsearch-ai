"""Sinh vector đa loại cho sản phẩm (name/profile/use_case/question), chỉ embed văn bản đổi (text_hash),
lượng tử hoá Int8 + lưu float32, có giới hạn tốc độ cho free tier."""
from __future__ import annotations

import asyncio
import time
from collections import deque

import numpy as np

from app import repo
from app.catalog.quant import quantize
from app.catalog.texts import text_hash, vector_texts
from app.db import bump_version
from app.gemini.pool import BaseGemini

TASK = "RETRIEVAL_DOCUMENT"


class RateLimiter:
    """Giới hạn số văn bản/phút (free tier tính mỗi văn bản trong batch là 1 request)."""

    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self.events: deque[tuple[float, int]] = deque()

    async def acquire(self, n: int) -> None:
        n = min(n, self.per_minute)
        while True:
            now = time.monotonic()
            while self.events and now - self.events[0][0] >= 60:
                self.events.popleft()
            used = sum(c for _, c in self.events)
            if used + n <= self.per_minute:
                self.events.append((now, n))
                return
            await asyncio.sleep(max(0.2, 60 - (now - self.events[0][0])))


async def embed_demo(pool, gem: BaseGemini, demo_id: int, *, per_minute: int, timeout_ms: int,
                     progress=None, batch: int = 50) -> dict:
    demo = await repo.get_demo_by_id(pool, demo_id)
    defs = await repo.list_defs(pool, demo_id)
    products = await repo.list_products(pool, demo_id)
    model, dim = demo["embed_model"], demo["embed_dim"]
    existing = await repo.existing_hashes(pool, demo_id)
    keep: set[tuple[int, str, str]] = set()
    todo: list[dict] = []
    for p in products:
        for kind, txt in vector_texts(p, defs):
            h = text_hash(model, dim, TASK, txt)
            keep.add((p["id"], kind, h))
            if (p["id"], kind, h) not in existing:
                todo.append({"product_id": p["id"], "kind": kind, "source_text": txt, "text_hash": h})
    todo = list({(t["product_id"], t["kind"], t["text_hash"]): t for t in todo}.values())
    limiter = RateLimiter(per_minute)
    batch = max(1, min(batch, per_minute))
    new_rows: list[dict] = []
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        await limiter.acquire(len(chunk))
        vecs = await gem.embed([c["source_text"] for c in chunk], TASK, call_type="embed_doc",
                               timeout_ms=timeout_ms, demo_id=demo_id, model=model, dim=dim)
        q, scale = quantize(vecs)
        for c, qi, si, vf in zip(chunk, q, scale, vecs):
            new_rows.append({**c, "embed_model": model, "vec_int8": qi.tobytes(), "scale": float(si),
                             "vec_f32": np.asarray(vf, np.float32).tobytes()})
        if progress:
            await progress(100.0 * min(len(todo), start + batch) / max(1, len(todo)))
    async with pool.acquire() as conn, conn.transaction():
        removed = await repo.replace_vectors(conn, demo_id, keep, new_rows)
        version = await bump_version(conn, demo_id)
    return {"embedded": len(new_rows), "reused": len(keep) - len(new_rows), "removed": removed,
            "total_vectors": len(keep), "data_version": version}
