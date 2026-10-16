"""Product Semantic Search — FastAPI app."""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app import repo
from app.accounts import AccountStore
from app.api import accounts_api, admin, auth, search, tables
from app.auth_google import make_google_verifier
from app.catalog.index import IndexManager
from app.config import Settings, get_settings
from app.db import VersionListener, create_pool, migrate
from app.gemini.pool import GeminiError, make_gemini
from app.jobs import JobRunner
from app.ingest.vectors import embed_demo
from app.keys import KeyStore
from app.logs import LogWriter
from app.search.pipeline import SearchService
from app.security import RedactFilter

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("app")


class VersionedAssets(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if re.search(r"-[A-Za-z0-9_-]{8,}\.(?:js|css|woff2?)$", path):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


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


async def seed_account(settings: Settings, accounts: AccountStore, pool) -> None:
    """Tạo sẵn tài khoản từ cấu hình (SEED_ACCOUNT_EMAIL/PASSWORD) nếu chưa có, và gán các bảng chưa có
    chủ cho tài khoản đầu tiên để tài khoản thấy ngay dữ liệu mẫu."""
    email = settings.seed_account_email.strip()
    if not email or not settings.seed_account_password:
        return
    acc = await accounts.ensure_account(email, settings.seed_account_password,
                                        name=settings.seed_account_name or None,
                                        phone=settings.seed_account_phone or None, is_admin=True)
    await pool.execute("UPDATE demos SET account_id=$1 WHERE account_id IS NULL", acc["id"])


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
        jobs = JobRunner(pool, settings.job_concurrency)

        async def embed_job(ctx, demo_id, params):
            # A later import can invalidate an in-flight snapshot. Re-plan from
            # the committed checkpoints, with a bounded number of restarts.
            fallback_model = None
            for attempt in range(3):
                try:
                    result = await embed_demo(pool, gem, demo_id, per_minute=settings.embed_doc_rpm,
                                              timeout_ms=settings.offline_timeout_ms,
                                              batch=settings.embed_batch_size, concurrency=settings.embed_concurrency,
                                              progress=ctx.progress, checkpoint=ctx.checkpoint,
                                              target_model=fallback_model)
                    if fallback_model and result["source_model"] != fallback_model:
                        activated = await repo.set_demo_embed_model(pool, demo_id, fallback_model,
                                                                   result["embed_dim"],
                                                                   expected_version=result["data_version"])
                        if not activated:
                            raise GeminiError("catalog_changed", "dữ liệu thay đổi trước khi kích hoạt vector GPT")
                        log.warning("activated completed GPT embedding for table %s: %s", demo_id, fallback_model)
                    demo = await repo.get_demo_by_id(pool, demo_id)
                    if demo:
                        await indexes.reload(demo["slug"])
                    return result
                except GeminiError as exc:
                    # Stage GPT checkpoints first. If GPT is also unavailable, keep
                    # the active model and all old vectors; never expose a half-built space.
                    if (exc.reason in ("quota_exhausted", "rate_limited", "breaker_open")
                            and fallback_model is None and settings.gpt_enabled and attempt < 2):
                        demo = await repo.get_demo_by_id(pool, demo_id)
                        if demo and demo["embed_model"] != settings.openai_embed_model:
                            fallback_model = settings.openai_embed_model
                            log.warning("Gemini %s: staging GPT vectors for table %s, model %s",
                                        exc.reason, demo_id, settings.openai_embed_model)
                            continue
                    if exc.reason != "catalog_changed" or attempt == 2:
                        raise

        jobs.register("embed", embed_job)
        keys = KeyStore(pool, settings.table_key_encryption_key.get_secret_value())
        await keys.start()
        accounts = AccountStore(pool)
        await accounts.start()
        await seed_account(settings, accounts, pool)
        svc = SearchService(settings, gem, indexes, pool, log_sink=logs.put)
        if settings.load_on_startup:
            await indexes.load_all()
        listener = VersionListener(settings.database_url, pool, indexes.reload, settings.version_poll_s,
                                   current=lambda slug: indexes.get(slug).version if indexes.get(slug) else -1)
        await listener.start()
        app.state.settings, app.state.pool, app.state.gemini = settings, pool, gem
        app.state.indexes, app.state.search, app.state.logs, app.state.jobs = indexes, svc, logs, jobs
        app.state.keys = keys
        app.state.accounts = accounts
        app.state.google_verify = make_google_verifier(settings)
        await jobs.recover()
        warm = asyncio.create_task(warmup(gem)) if gem.provider.startswith("gemini") else None
        try:
            yield
        finally:
            if warm:
                warm.cancel()
            await jobs.cancel_all()
            await keys.stop()
            await accounts.stop()
            await listener.stop()
            await logs.stop()
            await gem.close()
            await pool.close()

    app = FastAPI(title="Product Semantic Search", version="1.0.0", lifespan=lifespan,
                  default_response_class=ORJSONResponse)
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

    @app.middleware("http")
    async def private_auth_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/assets", VersionedAssets(directory=STATIC / "assets", check_dir=False), name="ui-assets")
    app.include_router(auth.router)
    app.include_router(accounts_api.router)
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
                             "embed": st.settings.gemini_embed_model, "dim": st.settings.embed_dim,
                             "fallback": {"enabled": st.settings.gpt_enabled,
                                          "llm": st.settings.openai_llm_model,
                                          "embed": st.settings.openai_embed_model}}
            svc = st.search
            out["cache"] = {"response": svc.resp_cache.stats(), "understand": svc.und_cache.stats(),
                            "embed": svc.emb_cache.stats()}
            out["log_queue"] = {"pending": st.logs.q.qsize(), "dropped": st.logs.dropped}
            out["jobs_running"] = list(st.jobs.tasks)
        return out

    @app.get("/", include_in_schema=False)
    async def ui():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/logo.png", include_in_schema=False)
    async def logo():
        return FileResponse(STATIC / "logo.png", media_type="image/png")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(STATIC / "favicon.ico", media_type="image/x-icon")

    @app.get("/favicon-32x32.png", include_in_schema=False)
    async def favicon32():
        return FileResponse(STATIC / "favicon-32x32.png", media_type="image/png")

    @app.get("/favicon-16x16.png", include_in_schema=False)
    async def favicon16():
        return FileResponse(STATIC / "favicon-16x16.png", media_type="image/png")

    @app.get("/apple-touch-icon.png", include_in_schema=False)
    async def apple_touch_icon():
        return FileResponse(STATIC / "apple-touch-icon.png", media_type="image/png")

    return app


app = create_app()
