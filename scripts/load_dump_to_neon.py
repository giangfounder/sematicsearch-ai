"""Nạp dữ liệu từ file pg_dump (plain) vào Neon/Postgres qua asyncpg (hỗ trợ SSL, không cần psql).
Chỉ nạp các bảng cốt lõi. Tạo schema bằng migrations của app rồi COPY dữ liệu.
Chạy: python -m scripts.load_dump_to_neon "<neon_dsn>" [reports/semsearch_dump.sql]"""
from __future__ import annotations

import asyncio
import io
import re
import sys
from pathlib import Path

from app.db import create_pool, migrate

TABLES = ["accounts", "demos", "attribute_definitions", "products", "product_vectors", "eval_cases", "table_keys"]
COPY_RE = re.compile(r"^COPY public\.(\w+) \((.*)\) FROM stdin;")


def parse_blocks(path: Path) -> dict[str, tuple[list[str], str]]:
    """Trích {table: (columns, data_text)} từ các khối COPY ... FROM stdin; ... \\."""
    blocks: dict[str, tuple[list[str], str]] = {}
    table = None
    cols: list[str] = []
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if table is None:
            m = COPY_RE.match(line)
            if m:
                table = m.group(1)
                cols = [c.strip().strip('"') for c in m.group(2).split(",")]
                buf = []
        elif line == r"\.":
            if table in TABLES:
                blocks[table] = (cols, "\n".join(buf) + "\n")
            table = None
        else:
            buf.append(line)
    return blocks


async def main() -> None:
    dsn = sys.argv[1].strip().strip('"').strip("'")
    dump = Path(sys.argv[2] if len(sys.argv) > 2 else "reports/semsearch_dump.sql")
    print(f"Đích: {dsn.split('@')[-1]}")
    blocks = parse_blocks(dump)
    print("Khối dữ liệu đọc được:", {t: len(d.splitlines()) for t, (_, d) in blocks.items()})
    pool = await create_pool(dsn)
    applied = await migrate(pool)
    print(f"Schema trên Neon: {applied or 'đã có'}")
    async with pool.acquire() as c:
        await c.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE")
        for t in TABLES:
            if t not in blocks:
                print(f"  {t}: (không có trong dump)")
                continue
            cols, data = blocks[t]
            if not data.strip():
                print(f"  {t}: 0 dòng")
                continue
            await c.copy_to_table(t, source=io.BytesIO(data.encode("utf-8")), columns=cols, format="text")
            print(f"  {t}: nạp xong")
        for t in TABLES:
            await c.execute(
                f"SELECT setval(pg_get_serial_sequence('{t}','id'), GREATEST((SELECT COALESCE(MAX(id),1) FROM {t}),1))")
        print("--- kiểm tra ---")
        for t in TABLES:
            print(f"  {t}: {await c.fetchval(f'SELECT count(*) FROM {t}')}")
    await pool.close()
    print("XONG.")


if __name__ == "__main__":
    asyncio.run(main())
