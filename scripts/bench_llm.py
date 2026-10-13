"""So sánh latency LLM cho bước understand với prompt thật của demo.
python -m scripts.bench_llm --demo dienmay --models gemini-3.5-flash-lite,gemini-3.1-flash-lite --n 12"""
from __future__ import annotations

import argparse
import asyncio
import time

import numpy as np

from app.catalog.index import load_index
from app.config import get_settings
from app.db import create_pool
from app.gemini.pool import GeminiError, GeminiPool
from app.search.understand import build_llm_request

QUERIES = ["dạ cho em hỏi tủ lạnh sam sung tầm 10 củ loại tiết kiệm điện", "ai phôn mười lăm pờ rô mác còn không",
           "máy giặt lồng đứng tầm 7 triệu", "điều hòa hai chiều cho phòng 20 mét vuông", "tivi bốn ba in giá rẻ",
           "nhà chung cư không có chỗ phơi đồ thì nên mua máy nào", "màu đen thì sao", "giá vàng hôm nay"]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default="dienmay")
    ap.add_argument("--models", default="gemini-3.5-flash-lite,gemini-3.1-flash-lite")
    ap.add_argument("--thinking", default="minimal,")
    ap.add_argument("--n", type=int, default=12)
    args = ap.parse_args()
    s = get_settings()
    pool = await create_pool(s.database_url)
    idx = await load_index(pool, args.demo)
    print(f"system prompt: {len(idx.understand_system)} ký tự")
    for model in args.models.split(","):
        for th in args.thinking.split(","):
            s2 = s.model_copy(update={"gemini_thinking_level": th})
            g = GeminiPool(s2)
            await g.start()
            lat, errs, toks = [], 0, []
            for i in range(args.n):
                q = QUERIES[i % len(QUERIES)]
                system, contents, schema = build_llm_request(idx, q, None, [])
                t0 = time.perf_counter()
                try:
                    await g.generate_json(system=system, contents=contents, schema=schema, call_type="understand",
                                          timeout_ms=15000, model=model, max_output_tokens=500)
                    lat.append((time.perf_counter() - t0) * 1000)
                except GeminiError as e:
                    errs += 1
                    print("  err", e.reason, str(e)[:120])
            u = g.usage.summary().get("understand", {})
            if lat:
                print(f"{model:24s} thinking={th or '(mặc định)':9s} p50={np.percentile(lat, 50):6.0f}ms "
                      f"p95={np.percentile(lat, 95):6.0f}ms min={min(lat):5.0f} lỗi={errs} "
                      f"tok in/out={u.get('input_tokens', 0) // max(1, len(lat))}/{u.get('output_tokens', 0) // max(1, len(lat))}")
            await g.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
