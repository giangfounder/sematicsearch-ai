"""Kết nối PostgreSQL (asyncpg), migration SQL đánh số, LISTEN/NOTIFY data_version."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

import asyncpg

log = logging.getLogger("db")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
CHANNEL = "demo_changed"


async def _init_conn(conn: asyncpg.Connection) -> None:
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=lambda v: json.dumps(v, ensure_ascii=False),
                                  decoder=json.loads, schema="pg_catalog")


async def create_pool(dsn: str, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    kw: dict = {}
    low = dsn.lower()
    # Neon/Supabase yêu cầu SSL; endpoint pooled (PgBouncer) không hỗ trợ prepared statement -> tắt cache.
    if "neon.tech" in low or "supabase" in low or "sslmode=require" in low or "pooler" in low:
        kw["statement_cache_size"] = 0
        if "sslmode=require" in low and "ssl=" not in low:
            import ssl as _ssl

            kw["ssl"] = _ssl.create_default_context()
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size, init=_init_conn,
                                     timeout=15, command_timeout=30,
                                     server_settings={"lock_timeout": "10000", "idle_in_transaction_session_timeout": "60000"},
                                     **kw)


async def migrate(pool: asyncpg.Pool) -> list[str]:
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
        # khoá để nhiều worker khởi động cùng lúc không migrate chồng nhau
        await conn.execute("SELECT pg_advisory_lock(727274)")
        try:
            done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
            for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if f.name in done:
                    continue
                async with conn.transaction():
                    await conn.execute(f.read_text(encoding="utf-8"))
                    await conn.execute("INSERT INTO schema_migrations(name) VALUES($1)", f.name)
                applied.append(f.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(727274)")
    return applied


async def bump_version(conn: asyncpg.Connection, demo_id: int) -> int:
    """Gọi bên trong transaction ghi dữ liệu: tăng data_version + NOTIFY (gửi khi commit)."""
    row = await conn.fetchrow(
        "UPDATE demos SET data_version = data_version + 1 WHERE id=$1 RETURNING slug, data_version", demo_id)
    await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, f"{row['slug']}:{row['data_version']}")
    return row["data_version"]


class VersionListener:
    """LISTEN demo_changed + poll định kỳ (phòng khi kết nối LISTEN rớt)."""

    def __init__(self, dsn: str, pool: asyncpg.Pool, on_change: Callable[[str, int], Awaitable[None]],
                 poll_s: float = 30.0, current: Callable[[str], int] | None = None):
        self.dsn, self.pool, self.on_change, self.poll_s = dsn, pool, on_change, poll_s
        self.conn: asyncpg.Connection | None = None
        self.task: asyncio.Task | None = None
        # version đang nạp thực tế (index trong RAM). Không giữ bản sao riêng: xoá rồi tạo lại bảng cùng slug
        # sẽ đếm version lại từ đầu, bản sao cũ sẽ chặn nhầm việc nạp lại.
        self.current = current or (lambda _slug: -1)

    def _cb(self, _conn, _pid, _channel, payload: str) -> None:
        slug, _, ver = payload.rpartition(":")
        try:
            v = int(ver)
        except ValueError:
            return
        asyncio.get_running_loop().create_task(self._fire(slug, v))

    async def _fire(self, slug: str, version: int) -> None:
        if self.current(slug) == version:
            return
        try:
            await self.on_change(slug, version)
        except Exception:  # noqa: BLE001
            log.exception("reload %s failed", slug)

    async def _connect(self) -> None:
        self.conn = await asyncpg.connect(self.dsn, timeout=15, command_timeout=30)
        await self.conn.add_listener(CHANNEL, self._cb)

    async def start(self) -> None:
        await self._connect()
        self.task = asyncio.create_task(self._poll())

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(self.poll_s)
            try:
                if self.conn is None or self.conn.is_closed():
                    await self._connect()
                rows = await self.pool.fetch("SELECT slug, data_version FROM demos")
                for r in rows:
                    await self._fire(r["slug"], r["data_version"])
            except Exception:  # noqa: BLE001
                log.exception("version poll failed")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
        if self.conn and not self.conn.is_closed():
            await self.conn.close()
