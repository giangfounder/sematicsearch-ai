"""Bounded real-API benchmark; catalog writes are intercepted in memory.

Run against the previous Docker image and the hotfix image with identical
synthetic input. Only a session-local temporary table is used for write timing.
No product, vector, account, or job in the production database is modified.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path.cwd()))

import numpy as np

from app import repo
from app.catalog.index import IndexManager
from app.config import Settings
from app.db import create_pool
from app.gemini.pool import make_gemini
from app.ingest import vectors
from app.search.pipeline import SearchService


class StatusCounts(logging.Handler):
    def __init__(self):
        super().__init__()
        self.codes = {}

    def emit(self, record):
        match = re.search(r'HTTP/\S+ (\d{3})', record.getMessage())
        if match:
            code = match[1]
            self.codes[code] = self.codes.get(code, 0) + 1


def percentiles(values):
    return {"n": len(values), "mean_ms": round(float(np.mean(values)), 2),
            "p50_ms": round(float(np.percentile(values, 50)), 2),
            "p95_ms": round(float(np.percentile(values, 95)), 2)} if values else {"n": 0}


async def main(args):
    settings = Settings()
    pool = await create_pool(settings.database_url, max_size=3)
    gem = make_gemini(settings)
    await gem.start()
    counts = StatusCounts()
    http_log = logging.getLogger("httpx")
    http_log.handlers = [counts]
    http_log.setLevel(logging.INFO)
    http_log.propagate = False
    original = {}
    saved = []
    original_bump = vectors.bump_version
    output = {"label": args.label, "scope": "synthetic_read_only_shadow_pipeline",
              "model": settings.gemini_embed_model, "dim": settings.embed_dim,
              "provider": gem.provider, "batch": args.batch, "concurrency": args.concurrency,
              "configured_documents_per_minute": settings.embed_doc_rpm}
    try:
        demo = await repo.get_demo_by_id(pool, args.demo_id)
        if demo is None:
            raise ValueError("benchmark demo does not exist")
        output["model"], output["dim"] = demo["embed_model"], demo["embed_dim"]
        products = [{"id": i + 1, "sku": f"B{i}", "name": f"Mẫu kiểm thử hiệu năng {i}",
                     "short_description": f"Nhu cầu sử dụng riêng cho mẫu {i}"} for i in range(args.products)]

        async def get_demo(*_args): return demo
        async def get_defs(*_args): return []
        async def get_products(*_args): return products
        async def get_hashes(*_args): return set()
        async def add(_conn, _did, rows):
            saved.extend(rows)
            return len(rows)
        async def replace(_conn, _did, _keep, rows):
            saved.extend(rows)
            return 0
        async def bump(*_args): return demo["data_version"]

        overrides = {"get_demo_by_id": get_demo, "list_defs": get_defs, "list_products": get_products,
                     "existing_hashes": get_hashes, "add_vectors": add, "replace_vectors": replace}
        for key, value in overrides.items():
            original[key] = getattr(repo, key, None)
            setattr(repo, key, value)
        vectors.bump_version = bump
        last_report = -1

        async def progress(p):
            nonlocal last_report
            bucket = int(p // 20)
            if bucket > last_report:
                last_report = bucket
                print(json.dumps({"event": "benchmark_progress", "label": args.label, "percent": round(p, 1)}), flush=True)

        kwargs = {"per_minute": settings.embed_doc_rpm, "timeout_ms": settings.offline_timeout_ms,
                  "batch": args.batch, "progress": progress}
        if "concurrency" in inspect.signature(vectors.embed_demo).parameters:
            kwargs["concurrency"] = args.concurrency
        started = time.perf_counter()
        result = await vectors.embed_demo(pool, gem, args.demo_id, **kwargs)
        elapsed = time.perf_counter() - started
        doc_lat = list(gem.usage.latencies.get("embed_doc", []))
        output["embedding"] = {"products": args.products, "vectors": result["embedded"],
                               "wall_s": round(elapsed, 3), "products_per_second": round(args.products / elapsed, 3),
                               "vectors_per_second": round(result["embedded"] / elapsed, 3),
                               "api_latency": percentiles(doc_lat), "http_statuses": dict(counts.codes)}
        for key, value in original.items():
            if value is None: delattr(repo, key)
            else: setattr(repo, key, value)
        original.clear()
        vectors.bump_version = original_bump

        # A temporary table has no defaults/FKs/sequences belonging to live data.
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("CREATE TEMP TABLE ingest_bench_vectors (product_id int, kind text, text_hash text, "
                               "source_text text, vec_int8 bytea, scale real, vec_f32 bytea) ON COMMIT DROP")
            rows = [(r["product_id"], r["kind"], r["text_hash"], r["source_text"], r["vec_int8"], r["scale"], r["vec_f32"])
                    for r in saved[:100]]
            started = time.perf_counter()
            await conn.executemany("INSERT INTO ingest_bench_vectors VALUES($1,$2,$3,$4,$5,$6,$7)", rows)
            output["database"] = {"rows": len(rows), "executemany_ms": round((time.perf_counter() - started) * 1000, 3),
                                  "scope": "session_local_temporary_table"}

        indexes = IndexManager(pool)
        await indexes.reload(demo["slug"])
        service = SearchService(settings, gem, indexes, pool, log_sink=None)
        queries = [p["name"] for p in indexes.get(demo["slug"]).products[:6]]
        cold, warm, top_ids = [], [], []
        for query in queries:
            started = time.perf_counter()
            response = await service.search(demo["slug"], {"text": query, "mode": "fast"}, use_cache=False)
            cold.append((time.perf_counter() - started) * 1000)
            top_ids.append([p["product_id"] for p in response["products"]])
        if queries:
            req = {"text": queries[0], "mode": "fast"}
            await service.search(demo["slug"], req)
            for _ in range(10):
                started = time.perf_counter()
                await service.search(demo["slug"], req)
                warm.append((time.perf_counter() - started) * 1000)
        output["search"] = {"mode": "fast", "query_type": "exact_product_names", "cold": percentiles(cold),
                            "warm_response_cache": percentiles(warm), "top_ids": top_ids,
                            "scope": "in_process_no_http_or_log_writes"}
        print(json.dumps({"event": "benchmark_result", **output}, ensure_ascii=False), flush=True)
    finally:
        for key, value in original.items():
            if value is None: delattr(repo, key)
            else: setattr(repo, key, value)
        vectors.bump_version = original_bump
        await gem.close()
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--demo-id", type=int, default=1)
    parser.add_argument("--products", type=int, default=90)
    parser.add_argument("--batch", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.products <= 100 or not 1 <= args.concurrency <= 2 or not 1 <= args.batch <= 50:
        parser.error("bounded probe supports <=100 products, <=2 workers, <=50 documents/batch")
    asyncio.run(main(args))
