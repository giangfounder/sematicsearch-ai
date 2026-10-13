"""Ghi search_logs bất đồng bộ (queue + batch) và flush bộ đếm token Gemini định kỳ."""
from __future__ import annotations

import asyncio
import logging

from app import repo

log = logging.getLogger("logs")


class LogWriter:
    def __init__(self, pool, gem=None, batch: int = 50, interval: float = 1.0, usage_interval: float = 30.0):
        self.pool, self.gem = pool, gem
        self.q: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self.batch, self.interval, self.usage_interval = batch, interval, usage_interval
        self.task: asyncio.Task | None = None
        self.dropped = 0

    def put(self, row: dict) -> None:
        try:
            self.q.put_nowait(row)
        except asyncio.QueueFull:
            self.dropped += 1

    async def start(self) -> None:
        self.task = asyncio.create_task(self._loop())

    async def _flush(self) -> None:
        rows = []
        while not self.q.empty() and len(rows) < 500:
            rows.append(self.q.get_nowait())
        if rows:
            try:
                await repo.insert_logs(self.pool, rows)
            except Exception:  # noqa: BLE001
                log.exception("insert logs failed (%d rows)", len(rows))

    async def _flush_usage(self) -> None:
        if self.gem is None:
            return
        try:
            await repo.flush_usage(self.pool, self.gem.usage.drain())
        except Exception:  # noqa: BLE001
            log.exception("flush usage failed")

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        last_usage = loop.time()
        while True:
            try:
                await asyncio.wait_for(self._wait_batch(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            await self._flush()
            if loop.time() - last_usage >= self.usage_interval:
                await self._flush_usage()
                last_usage = loop.time()

    async def _wait_batch(self) -> None:
        while self.q.qsize() < self.batch:
            await asyncio.sleep(0.05)

    async def flush_now(self) -> None:
        await self._flush()

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self._flush()
        await self._flush_usage()
