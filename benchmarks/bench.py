"""Benchmark tái sử dụng cho 2 mảng: (A) tạo embedding và (B) truy vấn search.

Ví dụ:
  python -m benchmarks.bench --what index,embed,search,quality --demo dienmay --out benchmarks/baseline.json
  python -m benchmarks.bench --what search --provider fake --search-n 40 --concurrency 8

Mặc định lấy provider từ .env; --provider fake chạy thuần nội bộ (embedding băm, không tốn API/quota).
Kết quả in ra màn hình và (nếu có --out) ghi JSON để so sánh trước/sau.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import numpy as np
import psutil

from app import repo
from app.catalog.index import IndexManager, load_index
from app.catalog.texts import vector_texts
from app.config import get_settings
from app.db import create_pool
from app.evals.evaluate import evaluate
from app.gemini.pool import make_gemini
from app.search.pipeline import SearchService

# giá Gemini embedding (USD / 1M token đầu vào) — chỉ để ước lượng chi phí, không phải số đo
EMBED_USD_PER_MTOK = 0.15


def pct(xs: list[float], q: float) -> float | None:
    return round(float(np.percentile(xs, q)), 1) if xs else None


def _stats(xs: list[float]) -> dict:
    return {"n": len(xs), "p50": pct(xs, 50), "p95": pct(xs, 95), "p99": pct(xs, 99),
            "max": round(max(xs), 1) if xs else None, "mean": round(float(np.mean(xs)), 1) if xs else None}


# ------------------------------------------------------------------ A) embedding
async def _texts_for(pool, slug: str, limit: int) -> tuple[list[str], int]:
    demo = await repo.get_demo(pool, slug)
    defs = await repo.list_defs(pool, demo["id"])
    products = await repo.list_products(pool, demo["id"])
    texts = [txt for p in products for _kind, txt in vector_texts(p, defs)]
    total = len(texts)
    return (texts[:limit] if limit else texts), total


async def embed_bench(gem, texts: list[str], *, batches: list[int], tasks: list[str], model: str, dim: int,
                      timeout_ms: int) -> dict:
    out: dict = {"n_texts": len(texts), "model": model, "dim": dim, "by_batch": {}}
    for b in batches:
        lats: list[float] = []
        t0 = time.perf_counter()
        embedded = 0
        for start in range(0, len(texts), b):
            chunk = texts[start:start + b]
            for task in tasks:
                s0 = time.perf_counter()
                await gem.embed(chunk, task, call_type="embed_doc", timeout_ms=timeout_ms, model=model, dim=dim)
                lats.append((time.perf_counter() - s0) * 1000)
            embedded += len(chunk)
        wall = time.perf_counter() - t0
        chars = sum(len(t) for t in texts) * len(tasks)
        toks = chars // 4
        out["by_batch"][str(b)] = {
            "calls": len(lats), "texts_embedded": embedded, "wall_s": round(wall, 2),
            "texts_per_s": round(embedded / wall, 1) if wall else None,
            "call_latency_ms": _stats(lats),
            "est_input_tokens": toks, "est_usd": round(toks / 1e6 * EMBED_USD_PER_MTOK, 5),
        }
    out["usage"] = gem.usage.summary()
    out["rate_limit"] = {k: b.state for k, b in gem.breakers.items()}
    return out


# ------------------------------------------------------------------ B) search
class _ReadOnlyIndexes:
    """Reuse the loaded catalog while keeping each cold request's caches private."""

    def __init__(self, source: IndexManager):
        self.source = source
        self.on_swap: list = []

    def get(self, slug: str):
        return self.source.get(slug)


async def search_bench(svc: SearchService, slug: str, queries: list[str], *, n: int, concurrency: int,
                       mode: str, cold: bool = True) -> dict:
    if not queries:
        raise ValueError(f"Demo {slug} không có câu hỏi đánh giá")
    if n < 1 or concurrency < 1:
        raise ValueError("--search-n và --concurrency phải >= 1")
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict] = []
    request_wall_ms: list[float] = []
    warm: list[float] = []

    async def one(q: str):
        async with sem:
            # Clearing shared caches inside concurrent requests races with in-flight work.
            # A fresh service has isolated understand/embed/rerank caches for this sample.
            runner = (SearchService(svc.s, svc.gem, _ReadOnlyIndexes(svc.indexes), svc.persist.pool)
                      if cold else svc)
            t0 = time.perf_counter()
            r = await runner.search(slug, {"text": q, "top_k": 3, "mode": mode},
                                    flags={"persistent_cache": False} if cold else None,
                                    use_cache=False)
            request_wall_ms.append((time.perf_counter() - t0) * 1000)
            rows.append(r)

    for q in (queries[-5:] if len(queries) > 5 else []):  # warmup trên câu khác (bỏ khỏi số đo)
        t0 = time.perf_counter()
        await svc.search(slug, {"text": q, "top_k": 3, "mode": mode}, use_cache=False)
        warm.append((time.perf_counter() - t0) * 1000)

    batch = (queries * ((n // max(1, len(queries))) + 1))[:n]
    t0 = time.perf_counter()
    await asyncio.gather(*(one(q) for q in batch))
    wall = time.perf_counter() - t0
    steps = {k: [r["latency_ms"].get(k, 0.0) for r in rows] for k in ("total", "understand", "embed", "retrieve", "rerank")
             if any(k in r["latency_ms"] for r in rows)}
    return {
        "n": n, "concurrency": concurrency, "mode": mode, "cold": cold, "wall_s": round(wall, 2),
        "qps": round(n / wall, 2) if wall else None,
        "warmup_ms": _stats(warm), "request_wall_ms": _stats(request_wall_ms),
        "latency_ms": {k: _stats(v) for k, v in steps.items()},
        "fallback_rate": round(sum(bool(r.get("fallback_reason")) for r in rows) / max(1, len(rows)), 3),
        "rerank_rate": round(sum(bool(r.get("reranked")) for r in rows) / max(1, len(rows)), 3),
    }


# ------------------------------------------------------------------ index (RAM)
async def index_bench(pool, demos: list[str]) -> dict:
    proc = psutil.Process()
    out: dict = {}
    for slug in demos:
        rss0 = proc.memory_info().rss
        t0 = time.perf_counter()
        idx = await load_index(pool, slug)
        ms = (time.perf_counter() - t0) * 1000
        if idx is None:
            out[slug] = None
            continue
        rss = proc.memory_info().rss
        out[slug] = {"n_products": idx.n, "n_vectors": idx.n_vectors, "build_ms": round(ms, 1),
                     "rss_delta_mb": round((rss - rss0) / 1e6, 1),
                     "vec_mb": round(((0 if idx.V8 is None else idx.V8.nbytes) +
                                      (0 if idx.Vf32 is None else idx.Vf32.nbytes)) / 1e6, 2)}
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", default="index,embed,search,quality")
    ap.add_argument("--demo", default="dienmay")
    ap.add_argument("--demos", default="", help="danh sách demo cho mục index (mặc định = --demo)")
    ap.add_argument("--provider", default="", help="ghi đè GEMINI_PROVIDER (gemini|fake)")
    ap.add_argument("--embed-limit", type=int, default=60)
    ap.add_argument("--embed-batches", default="50")
    ap.add_argument("--embed-tasks", default="RETRIEVAL_DOCUMENT")
    ap.add_argument("--embed-timeout-ms", type=int, default=60000)
    ap.add_argument("--search-n", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--mode", default="auto")
    ap.add_argument("--cold", action=argparse.BooleanOptionalAction, default=True,
                    help="xoá cache hiểu câu/embedding trước mỗi câu (đo nguội)")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.provider:
        os.environ["GEMINI_PROVIDER"] = args.provider
    get_settings.cache_clear()
    s = get_settings()
    want = set(args.what.split(","))

    pool = await create_pool(s.database_url)
    result: dict = {"meta": {"demo": args.demo, "provider": s.gemini_provider, "embed_model": s.gemini_embed_model,
                             "embed_dim": s.embed_dim, "mode": args.mode, "concurrency": args.concurrency,
                             "when": time.strftime("%Y-%m-%d %H:%M:%S")}}
    gem = make_gemini(s)
    await gem.start()
    try:
        if "index" in want:
            demos = args.demos.split(",") if args.demos else [args.demo]
            result["index"] = await index_bench(pool, demos)
            print("index:", json.dumps(result["index"], ensure_ascii=False))

        svc = None
        if want & {"search", "quality"}:
            indexes = IndexManager(pool)
            await indexes.reload(args.demo)
            svc = SearchService(s, gem, indexes, pool)

        if "embed" in want:
            texts, total = await _texts_for(pool, args.demo, args.embed_limit)
            batches = [int(x) for x in args.embed_batches.split(",")]
            tasks = args.embed_tasks.split(",")
            result["embed"] = await embed_bench(gem, texts, batches=batches, tasks=tasks,
                                                model=s.gemini_embed_model, dim=s.embed_dim,
                                                timeout_ms=args.embed_timeout_ms)
            result["embed"]["corpus_total_texts"] = total
            print("embed:", json.dumps(result["embed"]["by_batch"], ensure_ascii=False, indent=1))

        if "search" in want:
            cases = await repo.list_eval_cases(pool, (await repo.get_demo(pool, args.demo))["id"])
            queries = [c["query"] for c in cases]
            result["search"] = await search_bench(svc, args.demo, queries, n=args.search_n,
                                                  concurrency=args.concurrency, mode=args.mode, cold=args.cold)
            print("search:", json.dumps(result["search"], ensure_ascii=False))

        if "quality" in want:
            rep = await evaluate(svc, pool, args.demo, split=args.split, mode=args.mode, concurrency=args.concurrency)
            result["quality"] = {k: rep[k] for k in ("slug", "split", "mode", "n_cases", "n_product_cases",
                                                     "hit@1", "hit@3", "mrr", "status_accuracy", "matched_wrong_rate",
                                                     "rerank_rate", "fallback_rate", "latency_ms")}
            print("quality:", json.dumps(result["quality"], ensure_ascii=False))
    finally:
        await gem.close()
        await pool.close()

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
