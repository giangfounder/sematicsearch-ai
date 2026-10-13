"""Khoá API theo bảng: tra cứu trong RAM (không query DB trên đường search), ghi nhận lần dùng theo lô."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

log = logging.getLogger("keys")
SCOPES = ("read", "write")


def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode("utf-8")).hexdigest()


def new_key() -> str:
    return "sk_tbl_" + secrets.token_urlsafe(30)


class KeyStore:
    def __init__(self, pool):
        self.pool = pool
        self.by_hash: dict[str, dict] = {}
        self.used: dict[int, int] = {}
        self.task: asyncio.Task | None = None

    async def load(self) -> None:
        rows = await self.pool.fetch("""SELECT k.*, d.slug FROM table_keys k JOIN demos d ON d.id=k.demo_id""")
        self.by_hash = {r["key_hash"]: dict(r) for r in rows}

    async def start(self, refresh_s: float = 30.0) -> None:
        await self.load()
        self.task = asyncio.create_task(self._loop(refresh_s))

    async def _loop(self, refresh_s: float) -> None:
        while True:
            await asyncio.sleep(refresh_s)
            try:
                await self.flush()
                await self.load()  # đồng bộ khi chạy nhiều worker
            except Exception:  # noqa: BLE001
                log.exception("key refresh failed")

    async def flush(self) -> None:
        used, self.used = self.used, {}
        for kid, n in used.items():
            await self.pool.execute("UPDATE table_keys SET last_used_at=now(), use_count=use_count+$2 WHERE id=$1", kid, n)

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
        try:
            await self.flush()
        except Exception:  # noqa: BLE001
            pass

    def has_active(self, slug: str) -> bool:
        now = datetime.now(timezone.utc)
        return any(k["slug"] == slug and k["active"] and (k["expires_at"] is None or k["expires_at"] > now)
                   for k in self.by_hash.values())

    def check(self, raw: str | None, slug: str, scope: str) -> bool:
        if not raw:
            return False
        k = self.by_hash.get(hash_key(raw))
        if k is None or k["slug"] != slug or not k["active"] or scope not in k["scopes"]:
            return False
        if k["expires_at"] is not None and k["expires_at"] <= datetime.now(timezone.utc):
            return False
        self.used[k["id"]] = self.used.get(k["id"], 0) + 1
        return True

    # ---------- CRUD ----------
    async def list(self, demo_id: int) -> list[dict]:
        rows = await self.pool.fetch("""SELECT id, name, prefix, scopes, active, expires_at, created_at, last_used_at, use_count
                                        FROM table_keys WHERE demo_id=$1 ORDER BY created_at DESC""", demo_id)
        return [dict(r) for r in rows]

    async def create(self, demo_id: int, name: str, scopes: list[str], expires_days: int | None) -> tuple[str, dict]:
        raw = new_key()
        exp = datetime.now(timezone.utc) + timedelta(days=expires_days) if expires_days else None
        row = await self.pool.fetchrow(
            """INSERT INTO table_keys(demo_id, name, prefix, key_hash, scopes, expires_at) VALUES($1,$2,$3,$4,$5,$6)
               RETURNING id, name, prefix, scopes, active, expires_at, created_at, last_used_at, use_count""",
            demo_id, name, raw[:12], hash_key(raw), scopes, exp)
        await self.load()
        return raw, dict(row)

    async def update(self, demo_id: int, key_id: int, data: dict) -> dict | None:
        sets, args = [], [demo_id, key_id]
        for col in ("name", "scopes", "active"):
            if data.get(col) is not None:
                args.append(data[col])
                sets.append(f"{col}=${len(args)}")
        if "expires_days" in data:
            d = data["expires_days"]
            args.append(datetime.now(timezone.utc) + timedelta(days=d) if d else None)
            sets.append(f"expires_at=${len(args)}")
        if not sets:
            return None
        row = await self.pool.fetchrow(
            f"""UPDATE table_keys SET {', '.join(sets)} WHERE demo_id=$1 AND id=$2
                RETURNING id, name, prefix, scopes, active, expires_at, created_at, last_used_at, use_count""", *args)
        await self.load()
        return dict(row) if row else None

    async def delete(self, demo_id: int, key_id: int) -> bool:
        r = await self.pool.execute("DELETE FROM table_keys WHERE demo_id=$1 AND id=$2", demo_id, key_id)
        await self.load()
        return r.endswith("1")
