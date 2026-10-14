"""Đo latency end-to-end của pipeline search (p50/p95 từng bước) cho 1 demo, nhiều mode.
python -m scripts.bench_search --demo goi-cuoc --n 8 --modes fast,auto"""
from __future__ import annotations

import argparse
import asyncio
import time

import numpy as np

from app.catalog.index import IndexManager
from app.config import get_settings
from app.db import create_pool
from app.gemini.pool import make_gemini
from app.search.pipeline import SearchService

QUERIES = [
    "dạ cho em hỏi gói nào dùng cho cả nhà", "đi hàn quốc tuần sau dùng gói nào", "gói tóp tóp giá bao nhiêu",
    "gói rẻ cho sinh viên", "gói data xem phim nhiều", "có gói gọi nội mạng miễn phí không",
    "gói tầm 100 nghìn một tháng", "đăng ký gói cho con đi học",
]


def p(xs, q):
    return round(float(np.percentile(xs, q)), 0) if xs else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default="goi-cuoc")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--modes", default="fast,auto,accurate")
    ap.add_argument("--qfile", default="")
    ap.add_argument("--cold", action="store_true", help="xoá cache understand/embed mỗi câu (đo nguội)")
    args = ap.parse_args()
    s = get_settings()
    pool = await create_pool(s.database_url)
    gem = make_gemini(s)
    await gem.start()
    global QUERIES
    if args.qfile:
        QUERIES = [l.strip() for l in open(args.qfile, encoding="utf-8") if l.strip()]
    idx = IndexManager(pool)
    await idx.reload(args.demo)
    svc = SearchService(s, gem, idx, pool)
    for mode in args.modes.split(","):
        steps = {"total": [], "understand": [], "embed": [], "retrieve": [], "rerank": []}
        rr = 0
        for i in range(args.n):
            q = QUERIES[i % len(QUERIES)]
            if args.cold:
                svc.und_cache.clear(); svc.emb_cache.clear()
            r = await svc.search(args.demo, {"text": q, "top_k": 3, "mode": mode}, use_cache=False)
            for k in steps:
                v = r["latency_ms"].get(k, 0)
                if k != "rerank" or r["reranked"]:
                    steps[k].append(v)
            rr += r["reranked"]
        print(f"\n[mode={mode}] n={args.n}  rerank={rr}/{args.n}")
        for k in ("total", "understand", "embed", "retrieve", "rerank"):
            xs = steps[k]
            if xs:
                print(f"  {k:11s} p50={p(xs,50):6.0f}  p95={p(xs,95):6.0f}  max={max(xs):6.0f} ms")
    await gem.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
