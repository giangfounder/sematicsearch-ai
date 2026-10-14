"""Chuyển dữ liệu từ DB cục bộ sang Neon (hoặc Postgres bất kỳ) qua asyncpg (hỗ trợ SSL).
Chạy: python -m scripts.migrate_to_neon "postgresql://...neon.tech/neondb?sslmode=require"
Chỉ chuyển dữ liệu cốt lõi (bỏ phiên đăng nhập, log, cache để sạch)."""
from __future__ import annotations

import asyncio
import re
import sys

from app.config import get_settings
from app.db import create_pool, migrate

# thứ tự tôn trọng khoá ngoại
TABLES = ["accounts", "demos", "attribute_definitions", "products", "product_vectors", "eval_cases", "table_keys"]
SERIAL = ["accounts", "demos", "attribute_definitions", "products", "product_vectors", "eval_cases", "table_keys"]


async def main() -> None:
    dst_dsn = sys.argv[1].strip().strip('"').strip("'")
    src_dsn = re.sub(r"\s+", "", get_settings().database_url)
    print(f"Nguồn:  {src_dsn.split('@')[-1]}")
    print(f"Đích:   {dst_dsn.split('@')[-1]}")
    src = await create_pool(src_dsn)
    dst = await create_pool(dst_dsn)
    applied = await migrate(dst)
    print(f"Đã tạo schema trên đích (migrations: {applied or 'đã có sẵn'})")
    async with dst.acquire() as c:
        await c.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")
    for t in TABLES:
        rows = await src.fetch(f"SELECT * FROM {t} ORDER BY 1")
        if not rows:
            print(f"  {t}: 0 dòng")
            continue
        cols = list(rows[0].keys())
        recs = [tuple(r[c] for c in cols) for r in rows]
        async with dst.acquire() as c:
            await c.copy_records_to_table(t, records=recs, columns=cols)
        print(f"  {t}: {len(rows)} dòng")
    # đồng bộ sequence cho cột id tự tăng
    async with dst.acquire() as c:
        for t in SERIAL:
            await c.execute(
                f"SELECT setval(pg_get_serial_sequence('{t}','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM {t}),1))")
    # kiểm tra
    print("--- kiểm tra trên đích ---")
    async with dst.acquire() as c:
        for t in TABLES:
            n = await c.fetchval(f"SELECT count(*) FROM {t}")
            print(f"  {t}: {n}")
    await src.close()
    await dst.close()
    print("XONG.")


if __name__ == "__main__":
    asyncio.run(main())
