"""Job nền bền vững (bảng jobs): trạng thái/tiến độ ghi DB, không mất khi restart
(job đang chạy lúc restart được đánh dấu error 'interrupted')."""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from typing import Awaitable, Callable

from app import repo
from app.gemini.pool import redact

log = logging.getLogger("jobs")


class JobCtx:
    def __init__(self, pool, job_id: str):
        self.pool, self.id = pool, job_id
        self._last = 0.0

    async def progress(self, p: float, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last > 0.5:
            self._last = now
            await repo.update_job(self.pool, self.id, progress=round(min(100.0, max(0.0, p)), 1))


class JobRunner:
    def __init__(self, pool):
        self.pool = pool
        self.tasks: dict[str, asyncio.Task] = {}

    async def recover(self) -> None:
        await self.pool.execute("UPDATE jobs SET status='error', error='interrupted by restart', updated_at=now() "
                                "WHERE status IN ('queued','running')")

    async def submit(self, kind: str, demo_id: int | None, params: dict,
                     fn: Callable[[JobCtx], Awaitable[dict | None]]) -> str:
        job_id = f"{kind}_{uuid.uuid4().hex[:12]}"
        await repo.create_job(self.pool, job_id, demo_id, kind, params)
        self.tasks[job_id] = asyncio.create_task(self._run(job_id, fn))
        return job_id

    async def _run(self, job_id: str, fn) -> None:
        ctx = JobCtx(self.pool, job_id)
        try:
            await repo.update_job(self.pool, job_id, status="running")
            result = await fn(ctx)
            await repo.update_job(self.pool, job_id, status="done", progress=100.0, result=result or {})
        except asyncio.CancelledError:
            await repo.update_job(self.pool, job_id, status="cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            log.error("job %s failed: %s", job_id, redact(traceback.format_exc()))
            await repo.update_job(self.pool, job_id, status="error", error=redact(f"{type(e).__name__}: {e}")[:2000])
        finally:
            self.tasks.pop(job_id, None)

    async def wait(self, job_id: str) -> None:
        t = self.tasks.get(job_id)
        if t:
            await asyncio.gather(t, return_exceptions=True)

    async def cancel_all(self) -> None:
        for t in list(self.tasks.values()):
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
