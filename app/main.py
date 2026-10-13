"""Product Semantic Search — FastAPI app."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, ORJSONResponse

from app.api import admin, search, tables
from app.catalog.index import IndexManager
from app.config import Settings, get_settings
from app.db import VersionListener, create_pool, migrate
from app.gemini.pool import GeminiError, make_gemini
from app.jobs import JobRunner
from app.keys import KeyStore
from app.logs import LogWriter
from app.search.pipeline import SearchService
from app.security import RedactFilter

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("app")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in logging.getLogger().handlers:
        h.addFilter(RedactFilter())


async def warmup(gem) -> None:
    """Mở sẵn kết nối TLS tới Gemini để request đầu tiên không chịu chi phí bắt tay."""
    try:
        await gem.embed(["khởi động"], "RETRIEVAL_QUERY", call_type="embed_query", timeout_ms=5000)
    except GeminiError as e:
        log.warning("gemini warm-up failed: %s", e)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging()
        pool = await create_pool(settings.database_url)
        applied = await migrate(pool)
        if applied:
            log.info("migrations applied: %s", applied)
        gem = make_gemini(settings)
        await gem.start()
        indexes = IndexManager(pool)
        logs = LogWriter(pool, gem)
        await logs.start()
        jobs = JobRunner(pool)
        await jobs.recover()
        keys = KeyStore(pool)
        await keys.start()
        svc = SearchService(settings, gem, indexes, pool, log_sink=logs.put)
        if settings.load_on_startup:
            await indexes.load_all()
        listener = VersionListener(settings.database_url, pool, indexes.reload, settings.version_poll_s,
                                   current=lambda slug: indexes.get(slug).version if indexes.get(slug) else -1)
        await listener.start()
        app.state.settings, app.state.pool, app.state.gemini = settings, pool, gem
        app.state.indexes, app.state.search, app.state.logs, app.state.jobs = indexes, svc, logs, jobs
        app.state.keys = keys
        warm = asyncio.create_task(warmup(gem)) if gem.provider == "gemini" else None
        try:
            yield
        finally:
            if warm:
                warm.cancel()
            await jobs.cancel_all()
            await keys.stop()
            await listener.stop()
            await logs.stop()
            await gem.close()
            await pool.close()

    app = FastAPI(title="Product Semantic Search", version="1.0.0", lifespan=lifespan,
                  default_response_class=ORJSONResponse)
    app.include_router(search.router)
    app.include_router(admin.router)
    app.include_router(tables.public)
    app.include_router(tables.admin)

    @app.get("/health")
    async def health(request: Request, full: bool = False):
        st = request.app.state
        out = {"status": "ok", "demos": st.indexes.versions(), "provider": st.gemini.provider}
        try:
            await st.pool.fetchval("SELECT 1")
        except Exception:  # noqa: BLE001
            out["status"] = "degraded"
            out["db"] = "down"
        if full:
            from app.security import _match

            if st.settings.admin_key_set and not _match(request.headers.get("x-admin-key"), st.settings.admin_key_set):
                return out
            out["gemini"] = st.gemini.health()
            out["models"] = {"llm": st.settings.gemini_llm_model, "rerank": st.settings.gemini_rerank_model,
                             "embed": st.settings.gemini_embed_model, "dim": st.settings.embed_dim}
            svc = st.search
            out["cache"] = {"response": svc.resp_cache.stats(), "understand": svc.und_cache.stats(),
                            "embed": svc.emb_cache.stats()}
            out["log_queue"] = {"pending": st.logs.q.qsize(), "dropped": st.logs.dropped}
            out["jobs_running"] = list(st.jobs.tasks)
        return out

    @app.get("/", include_in_schema=False)
    async def ui():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
