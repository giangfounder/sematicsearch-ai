"""Smoke test Gemini: quyền truy cập model, structured output, embedding 768, latency.
Chạy: python -m scripts.smoke_gemini [--models gemini-2.5-flash-lite,gemini-3.5-flash-lite] [--n 10]"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import numpy as np

from app.config import get_settings
from app.gemini.pool import GeminiError, GeminiPool

SCHEMA = {"type": "object", "properties": {
    "intent": {"type": "string", "enum": ["find_product", "out_of_scope"]},
    "rewritten_query": {"type": "string"},
    "price_max": {"type": ["number", "null"]}},
    "required": ["intent", "rewritten_query"]}
SYSTEM = "Phân tích câu hỏi mua hàng. Giá trả về bằng VND. 'củ' = triệu."
QUERIES = ["dạ cho em hỏi tủ lạnh sam sung dưới mười củ", "ai phôn mười lăm pro max còn hàng không",
           "máy giặt cửa trước tầm tám triệu", "thời tiết hôm nay thế nào"]


def pct(xs, p):
    return round(float(np.percentile(xs, p)), 1) if xs else None


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()
    s = get_settings()
    g = GeminiPool(s)
    await g.start()
    print(f"keys: {len(s.gemini_keys)} | embed model: {s.gemini_embed_model} dim={s.embed_dim}")
    try:
        lat = []
        for i in range(args.n):
            t0 = time.perf_counter()
            v = await g.embed([QUERIES[i % len(QUERIES)]], "RETRIEVAL_QUERY", call_type="embed_query", timeout_ms=5000)
            lat.append((time.perf_counter() - t0) * 1000)
        print(f"[embed] OK shape={v.shape} norm={np.linalg.norm(v[0]):.4f} p50={pct(lat,50)}ms p95={pct(lat,95)}ms")
    except GeminiError as e:
        print(f"[embed] FAIL {e}")
    models = [m for m in (args.models or s.gemini_llm_model).split(",") if m]
    for m in models:
        lat, out = [], None
        try:
            for i in range(args.n):
                t0 = time.perf_counter()
                out = await g.generate_json(system=SYSTEM, contents=QUERIES[i % len(QUERIES)], schema=SCHEMA,
                                            call_type="understand", timeout_ms=10000, model=m, max_output_tokens=200)
                lat.append((time.perf_counter() - t0) * 1000)
            print(f"[llm {m}] OK p50={pct(lat,50)}ms p95={pct(lat,95)}ms min={min(lat):.0f} sample={out}")
        except GeminiError as e:
            print(f"[llm {m}] FAIL {e}")
    print("usage:", g.usage.summary())
    await g.close()


if __name__ == "__main__":
    asyncio.run(main())
