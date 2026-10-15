"""Sinh vector đa loại cho sản phẩm (name/profile/use_case/question), chỉ embed văn bản đổi (text_hash),
lượng tử hoá Int8 + lưu float32, có giới hạn tốc độ cho free tier."""
from __future__ import annotations

import asyncio
import time
import logging
import json
import random
from collections import deque

import numpy as np
import asyncpg

from app import repo
from app.catalog.quant import quantize
from app.catalog.texts import text_hash, vector_texts
from app.db import bump_version
from app.gemini.pool import BaseGemini, GeminiError

TASK = "RETRIEVAL_DOCUMENT"
log = logging.getLogger("embedding")


class PartialEmbeddingError(GeminiError):
    def __init__(self, result: dict):
        self.result = result
        super().__init__("partial_failure", f"{result['failed_vectors']} vector lỗi; phần đã lưu được giữ lại để thử tiếp")


class RateLimiter:
    """Giới hạn số văn bản/phút (free tier tính mỗi văn bản trong batch là 1 request)."""

    def __init__(self, per_minute: int, window_s: float = 60.0):
        self.per_minute = max(1, per_minute)
        self.window_s = window_s
        self.events: deque[tuple[float, int]] = deque()

    async def acquire(self, n: int) -> None:
        if n < 1 or n > self.per_minute:
            raise ValueError("rate limiter request must be within its capacity")
        while True:
            now = time.monotonic()
            while self.events and now - self.events[0][0] >= self.window_s:
                self.events.popleft()
            used = sum(c for _, c in self.events)
            if used + n <= self.per_minute:
                self.events.append((now, n))
                return
            await asyncio.sleep(max(0.001, self.window_s - (now - self.events[0][0])))


async def embed_demo(pool, gem: BaseGemini, demo_id: int, *, per_minute: int, timeout_ms: int,
                     progress=None, batch: int = 30, concurrency: int = 2, checkpoint=None) -> dict:
    started = time.perf_counter()
    # A coherent catalog snapshot; no database connection is held during API calls
    # or quota waits. The revision is checked again at every write.
    async with pool.acquire() as conn, conn.transaction(isolation="repeatable_read"):
        demo = await repo.get_demo_by_id(conn, demo_id)
        if demo is None:
            raise GeminiError("catalog_deleted", "bảng dữ liệu đã bị xóa")
        defs = await repo.list_defs(conn, demo_id)
        products = await repo.list_products(conn, demo_id)
        existing = await repo.existing_hashes(conn, demo_id)
    model, dim = demo["embed_model"], demo["embed_dim"]
    version = demo["data_version"]
    keep: set[tuple[int, str, str]] = set()
    todo: list[dict] = []
    for p in products:
        for kind, txt in vector_texts(p, defs):
            h = text_hash(model, dim, TASK, txt)
            keep.add((p["id"], kind, h))
            if (p["id"], kind, h) not in existing:
                todo.append({"product_id": p["id"], "kind": kind, "source_text": txt, "text_hash": h})
    todo = list({(t["product_id"], t["kind"], t["text_hash"]): t for t in todo}.values())
    # One limiter per provider, shared across catalogs and jobs in this process.
    # Group identical texts so repeated profiles only consume one API document.
    limiter = getattr(gem, "doc_limiter", None)
    if limiter is None or limiter.per_minute != max(1, per_minute):
        limiter = gem.doc_limiter = RateLimiter(per_minute)
    batch = max(1, min(batch, limiter.per_minute, 100))
    grouped: dict[str, list[dict]] = {}
    for row in todo:
        grouped.setdefault(row["text_hash"], []).append(row)
    groups = list(grouped.values())
    chunks = iter([groups[i:i + batch] for i in range(0, len(groups), batch)])
    write_lock = asyncio.Lock()
    embedded = 0
    reused = len(keep & existing)
    completed = reused
    api_documents = 0
    failed: list[dict] = []
    api_ms: list[float] = []
    rate_wait_ms = db_write_ms = 0.0
    plan_ms = (time.perf_counter() - started) * 1000

    def result_snapshot():
        elapsed = time.perf_counter() - started
        return {"embedded": embedded, "reused": reused, "removed": 0, "api_documents": api_documents,
                "retained_obsolete": len(existing - keep),
                "completed_vectors": completed, "total_vectors": len(keep), "failed_vectors": len(failed),
                "dead_letters": list(failed), "data_version": version,
                "timing_ms": {"plan": round(plan_ms, 2), "api_total": round(sum(api_ms), 2),
                              "api_mean": round(float(np.mean(api_ms)), 2) if api_ms else None,
                              "api_calls": len(api_ms), "rate_wait": round(rate_wait_ms, 2),
                              "db_write": round(db_write_ms, 2), "wall": round(elapsed * 1000, 2)},
                "vectors_per_second": round(embedded / max(elapsed, .000001), 3)}

    async def report(stage: str):
        p = 99.0 * completed / max(1, len(keep))
        if checkpoint:
            await checkpoint({"stage": stage, **result_snapshot()}, p)
        elif progress:
            await progress(p)

    async def save_once(rows: list[dict]):
        nonlocal version, db_write_ms
        t0 = time.perf_counter()
        async with pool.acquire() as conn, conn.transaction():
            current = await conn.fetchval("SELECT data_version FROM demos WHERE id=$1 FOR UPDATE", demo_id)
            if current is None:
                raise GeminiError("catalog_deleted", "bảng dữ liệu đã bị xóa")
            if current != version:
                raise GeminiError("catalog_changed", "dữ liệu thay đổi trong lúc embedding; cần nạp lại phần còn thiếu")
            # Append-only recovery: retain older vectors in storage. Index loading
            # ignores obsolete hashes; physical cleanup requires a separate,
            # explicitly approved maintenance operation.
            removed = 0
            await repo.add_vectors(conn, demo_id, rows)
            next_version = await bump_version(conn, demo_id)
        version = next_version
        db_write_ms += (time.perf_counter() - t0) * 1000
        return removed

    async def save(rows: list[dict]):
        for attempt in range(3):
            try:
                return await save_once(rows)
            except (asyncpg.PostgresConnectionError, asyncpg.SerializationError,
                    asyncpg.DeadlockDetectedError, asyncio.TimeoutError, OSError):
                if attempt == 2:
                    raise
                log.warning(json.dumps({"event": "embedding_db_retry", "demo_id": demo_id,
                                        "attempt": attempt + 1}))
                await asyncio.sleep(.2 * 2 ** attempt + random.uniform(0, .1))

    async def process(chunk):
        nonlocal embedded, completed, api_documents, rate_wait_ms
        async with gem.doc_sem:
            t0 = time.perf_counter()
            await limiter.acquire(len(chunk))
            rate_wait_ms += (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            try:
                vecs = await gem.embed([c["source_text"] for c in chunk], TASK, call_type="embed_doc",
                                       timeout_ms=timeout_ms, demo_id=demo_id, model=model, dim=dim)
            finally:
                api_ms.append((time.perf_counter() - t0) * 1000)
        try:
            vecs = np.asarray(vecs, dtype=np.float32)
        except (ValueError, TypeError) as exc:
            raise GeminiError("bad_output", "không đọc được vector Gemini") from exc
        if (vecs.shape != (len(chunk), dim) or not np.isfinite(vecs).all()
                or np.any(np.linalg.norm(vecs, axis=1) == 0)):
            raise GeminiError("bad_output", "Gemini trả vector rỗng, sai kích thước hoặc không hữu hạn")
        q, scale = quantize(vecs)
        new_rows = []
        for c, qi, si, vf in zip(chunk, q, scale, vecs):
            for target in grouped[c["text_hash"]]:
                new_rows.append({**target, "embed_model": model, "vec_int8": qi.tobytes(), "scale": float(si),
                                 "vec_f32": vf.tobytes()})
        async with write_lock:
            await save(new_rows)
            embedded += len(new_rows)
            completed += len(new_rows)
            api_documents += len(chunk)
            await report("embedding")

    async def guarded(chunk):
        try:
            await process(chunk)
        except GeminiError as exc:
            # A malformed document must not discard its healthy neighbors. Quota,
            # configuration and catalog-revision errors stop promptly instead of
            # recursively retrying every document with the same global failure.
            if exc.reason not in ("invalid_input", "bad_output", "timeout", "unavailable"):
                raise
            if exc.reason in ("invalid_input", "bad_output") and len(chunk) > 1:
                mid = len(chunk) // 2
                await guarded(chunk[:mid])
                await guarded(chunk[mid:])
                return
            async with write_lock:
                for row in chunk:
                    failed.extend({"product_id": target["product_id"], "kind": target["kind"],
                                   "text_hash": target["text_hash"], "reason": exc.reason}
                                  for target in grouped[row["text_hash"]])
                await report("embedding_with_errors")
                log.warning(json.dumps({"event": "embedding_batch_failed", "demo_id": demo_id,
                                        "documents": len(chunk), "reason": exc.reason}))

    async def worker():
        for chunk in chunks:
            await guarded([group[0] for group in chunk])

    await report("embedding")
    workers = [asyncio.create_task(worker()) for _ in range(max(1, min(concurrency, 8, len(groups))))]
    try:
        # gather alone would leave sibling workers running after the first failure.
        await asyncio.gather(*workers)
    finally:
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    await save([])
    result = result_snapshot()
    log.info(json.dumps({"event": "embedding_completed", "demo_id": demo_id,
                         **{k: v for k, v in result.items() if k != "dead_letters"}}))
    if failed:
        raise PartialEmbeddingError(result)
    if progress:
        await progress(100.0)
    return result
