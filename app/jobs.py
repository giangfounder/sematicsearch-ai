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

    async def checkpoint(self, result: dict, progress: float) -> None:
        await repo.update_job(self.pool, self.id, result=result, progress=round(progress, 1))


class JobRunner:
    def __init__(self, pool, max_concurrency: int = 2):
        self.pool = pool
        self.tasks: dict[str, asyncio.Task] = {}
        self.handlers: dict[str, Callable] = {}
        self.sem = asyncio.Semaphore(max(1, max_concurrency))
        self._submit_lock = asyncio.Lock()
        self._catalog_locks: dict[int, asyncio.Lock] = {}
        self._active: dict[str, tuple] = {}

    def register(self, kind: str, handler: Callable) -> None:
        self.handlers[kind] = handler

    async def recover(self) -> None:
        rows = await self.pool.fetch("SELECT * FROM jobs WHERE status IN ('queued','running') "
                                     "OR (kind='embed' AND status='error' AND error='interrupted by restart') "
                                     "ORDER BY created_at")
        for row in rows:
            kind = row["kind"]
            if kind in self.handlers:
                await repo.update_job(self.pool, row["id"], status="queued", error=None)
                self._launch(row["id"], kind, row["demo_id"], row["params"] or {}, None)
            else:
                await repo.update_job(self.pool, row["id"], status="error", error="interrupted by restart")

    async def submit(self, kind: str, demo_id: int | None, params: dict,
                     fn: Callable[[JobCtx], Awaitable[dict | None]] | None = None) -> str:
        if fn is None and kind not in self.handlers:
            raise ValueError(f"no handler for {kind}")
        async with self._submit_lock:
            signature = (kind, demo_id, params.get("requested_version"))
            if kind == "embed":
                for job_id, active in self._active.items():
                    if active == signature:
                        return job_id
            job_id = f"{kind}_{uuid.uuid4().hex[:12]}"
            await repo.create_job(self.pool, job_id, demo_id, kind, params)
            self._launch(job_id, kind, demo_id, params, fn)
            return job_id

    def _launch(self, job_id, kind, demo_id, params, fn):
        self._active[job_id] = (kind, demo_id, params.get("requested_version"))
        self.tasks[job_id] = asyncio.create_task(self._run(job_id, kind, demo_id, params, fn))

    async def _run(self, job_id: str, kind, demo_id, params, fn) -> None:
        ctx = JobCtx(self.pool, job_id)
        try:
            # Take the catalog lock BEFORE the global slot so queued work for
            # one table cannot block unrelated catalogs.
            lock = self._catalog_locks.setdefault(demo_id, asyncio.Lock()) if kind == "embed" else asyncio.Lock()
            async with lock, self.sem:
                await repo.update_job(self.pool, job_id, status="running", error=None)
                result = await fn(ctx) if fn else await self.handlers[kind](ctx, demo_id, params)
            await repo.update_job(self.pool, job_id, status="done", progress=100.0, result=result or {})
        except asyncio.CancelledError:
            # Registered jobs are resumable after an orderly shutdown as well as
            # after a crash. Batch vectors have already been committed.
            await repo.update_job(self.pool, job_id, status="queued" if kind in self.handlers else "cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            log.error("job %s failed: %s", job_id, redact(traceback.format_exc()))
            fields = {"status": "error", "error": redact(f"{type(e).__name__}: {e}")[:2000]}
            if isinstance(getattr(e, "result", None), dict):
                fields["result"] = e.result
            await repo.update_job(self.pool, job_id, **fields)
        finally:
            self.tasks.pop(job_id, None)
            self._active.pop(job_id, None)

    async def wait(self, job_id: str) -> None:
        t = self.tasks.get(job_id)
        if t:
            await asyncio.gather(t, return_exceptions=True)

    async def cancel_all(self) -> None:
        for t in list(self.tasks.values()):
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
