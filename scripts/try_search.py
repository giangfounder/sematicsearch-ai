"""Thử nhanh vài câu với cấu hình .env (không cần chạy server).
python -m scripts.try_search dienmay "câu 1" "câu 2" ... [--mode auto]"""
from __future__ import annotations

import asyncio
import json
import sys

from app.catalog.index import IndexManager
from app.config import get_settings
from app.db import create_pool
from app.gemini.pool import make_gemini
from app.search.pipeline import SearchService


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mode = "accurate" if "--accurate" in sys.argv else "fast" if "--fast" in sys.argv else "auto"
    slug, queries = args[0], args[1:]
    s = get_settings()
    pool = await create_pool(s.database_url)
    gem = make_gemini(s)
    await gem.start()
    idx = IndexManager(pool)
    await idx.reload(slug)
    svc = SearchService(s, gem, idx, pool)
    for q in queries:
        r = await svc.search(slug, {"text": q, "top_k": 3, "mode": mode, "debug": True}, use_cache=False)
        u = r["understanding"]
        print(f"\n>>> {q}\n  status={r['status']} reranked={r['reranked']} fallback={r['fallback_reason']} "
              f"lat={r['latency_ms']}\n  intent={u['intent']} rewritten={u['rewritten_query']!r}\n  filters="
              + json.dumps(u["filters"], ensure_ascii=False))
        if r["clarify_question"]:
            print("  clarify:", r["clarify_question"])
        for p in r["products"]:
            print(f"  #{p['rank']} {p['name']} score={p['score']} ({p['confidence']}) – {p['reason']}")
        for c in r["debug"]["candidates"][:3]:
            print(f"     dbg {c['name'][:40]:40s} cos={c['dense'].get('cos_f32')} bm25={c['bm25']} ent={c['entity']} "
                  f"rrf={c['rrf']} soft={c['soft']} raw={c['raw']} final={c['final']} rr={c['rerank']}")
    await gem.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
