"""Cache RAM (TTL + LRU) có chống dồn request (1 future / key) + cache bền trong Postgres (tuỳ chọn)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Awaitable, Callable

import numpy as np
from cachetools import TTLCache

log = logging.getLogger("cache")


def hkey(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class AsyncTTL:
    def __init__(self, maxsize: int, ttl: float):
        self.data: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self.inflight: dict[str, asyncio.Future] = {}
        self.hits = self.misses = 0

    def get(self, key: str):
        v = self.data.get(key)
        if v is None:
            self.misses += 1
        else:
            self.hits += 1
        return v

    def set(self, key: str, value) -> None:
        self.data[key] = value

    async def get_or_compute(self, key: str, fn: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
        v = self.data.get(key)
        if v is not None:
            self.hits += 1
            return v, True
        fut = self.inflight.get(key)
        if fut is not None:
            return await asyncio.shield(fut), True
        self.misses += 1
        fut = asyncio.get_running_loop().create_future()
        self.inflight[key] = fut
        try:
            v = await fn()
            if v is not None:
                self.data[key] = v
            fut.set_result(v)
            return v, False
        except BaseException as e:
            fut.set_exception(e)
            fut.exception()  # tránh cảnh báo "exception never retrieved"
            raise
        finally:
            self.inflight.pop(key, None)

    def clear(self) -> None:
        self.data.clear()

    def stats(self) -> dict:
        return {"size": len(self.data), "hits": self.hits, "misses": self.misses}


class PersistentCache:
    """Bảng llm_cache. Chỉ dùng cho embedding câu hỏi và understanding (không cho response)."""

    def __init__(self, pool):
        self.pool = pool

    async def get_vec(self, key: str) -> np.ndarray | None:
        if self.pool is None:
            return None
        try:
            b = await self.pool.fetchval("SELECT vec FROM llm_cache WHERE key=$1", key)
        except Exception:  # noqa: BLE001
            return None
        return np.frombuffer(b, dtype=np.float32).copy() if b else None

    async def put_vec(self, key: str, vec: np.ndarray) -> None:
        if self.pool is None:
            return
        try:
            await self.pool.execute("INSERT INTO llm_cache(key, kind, vec) VALUES($1,'embed',$2) ON CONFLICT (key) DO NOTHING",
                                    key, np.asarray(vec, np.float32).tobytes())
        except Exception:  # noqa: BLE001
            log.warning("persist vec failed")

    async def get_json(self, key: str) -> dict | None:
        if self.pool is None:
            return None
        try:
            return await self.pool.fetchval("SELECT value FROM llm_cache WHERE key=$1", key)
        except Exception:  # noqa: BLE001
            return None

    async def put_json(self, key: str, value: dict) -> None:
        if self.pool is None:
            return
        try:
            await self.pool.execute("INSERT INTO llm_cache(key, kind, value) VALUES($1,'understand',$2) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, created_at=now()",
                                    key, value)
        except Exception:  # noqa: BLE001
            log.warning("persist json failed")
