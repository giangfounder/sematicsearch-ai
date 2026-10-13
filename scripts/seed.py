"""Nạp 3 demo mẫu (seeds/<slug>/demo.json + eval_cases.json) vào DB và sinh vector.
python -m scripts.seed [--only dienmay] [--reset] [--no-embed]"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from app import repo
from app.config import get_settings
from app.db import bump_version, create_pool, migrate
from app.gemini.pool import make_gemini
from app.ingest.vectors import embed_demo

SEEDS = Path(__file__).resolve().parent.parent / "seeds"
SLUGS = ["dienmay", "vienthong", "batdongsan"]


async def load_one(pool, slug: str, reset: bool) -> int:
    data = json.loads((SEEDS / slug / "demo.json").read_text(encoding="utf-8"))
    cases = json.loads((SEEDS / slug / "eval_cases.json").read_text(encoding="utf-8"))
    d = await repo.get_demo(pool, slug)
    if d and reset:
        await repo.delete_demo(pool, d["id"])
        d = None
    if d is None:
        d = await repo.create_demo(pool, {**data["demo"], "embed_model": get_settings().gemini_embed_model,
                                          "embed_dim": get_settings().embed_dim})
    async with pool.acquire() as conn, conn.transaction():
        await repo.upsert_defs(conn, d["id"], data["definitions"], replace=True)
        ids = await repo.upsert_products(conn, d["id"], data["products"], mode="replace")
        await bump_version(conn, d["id"])
    rows = []
    for c in cases:
        ctx = c.get("context")
        if ctx:
            ctx = {"previous_text": ctx.get("previous_text"),
                   "previous_product_ids": [ids[s] for s in ctx.get("previous_skus", [])]}
        rows.append({"query": c["query"], "context": ctx, "expected_product_ids": [ids[s] for s in c["expected_skus"]],
                     "expected_status": c["expected_status"], "category": c["category"], "split": c["split"],
                     "source": c.get("source", "manual")})
    await repo.delete_eval_cases(pool, d["id"], "manual")
    await repo.insert_eval_cases(pool, d["id"], rows)
    print(f"[{slug}] {len(ids)} sản phẩm, {len(rows)} eval cases")
    return d["id"]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    pool = await create_pool(s.database_url)
    await migrate(pool)
    gem = make_gemini(s)
    await gem.start()
    try:
        for slug in [x for x in SLUGS if not args.only or x in args.only.split(",")]:
            demo_id = await load_one(pool, slug, args.reset)
            if args.no_embed:
                continue
            t0 = time.time()

            async def prog(p, slug=slug):
                print(f"  [{slug}] embed {p:.0f}%", flush=True)

            res = await embed_demo(pool, gem, demo_id, per_minute=s.embed_doc_rpm, timeout_ms=s.offline_timeout_ms,
                                   progress=prog)
            print(f"[{slug}] vectors: {res} ({time.time() - t0:.0f}s)", flush=True)
    finally:
        await gem.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
