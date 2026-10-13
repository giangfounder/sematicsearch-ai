"""API quản trị: demos, definitions, products, import, template, embed, enrich, eval_cases, jobs, evaluate,
calibrate, logs. Mọi thay đổi dữ liệu tăng data_version -> NOTIFY -> nạp lại cache."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app import repo
from app.db import bump_version
from app.evals.calibrate import calibrate
from app.evals.evaluate import evaluate
from app.evals.generate import generate_cases
from app.ingest.enrich import apply_enrich, run_enrich
from app.ingest.importer import apply_import, plan_import
from app.ingest.template_xlsx import build_template
from app.ingest.vectors import embed_demo
from app.schemas import (AttributeDef, DemoCreate, DemoPatch, EnrichApply, EnrichRequest, EvalCaseIn,
                         EvaluateRequest, GenerateEvalRequest, ProductIn, ProductPatch)
from app.security import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


def st(request: Request):
    return request.app.state


async def demo_or_404(request: Request, slug: str) -> dict:
    d = await repo.get_demo(st(request).pool, slug)
    if d is None:
        raise HTTPException(404, f"demo '{slug}' không tồn tại")
    return d


async def submit_embed(request: Request, demo_id: int) -> str:
    s = st(request)

    async def job(ctx):
        return await embed_demo(s.pool, s.gemini, demo_id, per_minute=s.settings.embed_doc_rpm,
                                timeout_ms=s.settings.offline_timeout_ms, progress=ctx.progress)

    return await s.jobs.submit("embed", demo_id, {}, job)


async def after_write(request: Request, slug: str) -> None:
    """Nạp lại ngay trong process này (NOTIFY phục vụ các worker khác)."""
    await st(request).indexes.reload(slug)


# ---------------------------------------------------------------- demos
@router.get("/v1/admin/demos")
async def list_demos(request: Request):
    return await repo.list_demos(st(request).pool)


@router.post("/v1/admin/demos", status_code=201)
async def create_demo(body: DemoCreate, request: Request):
    if await repo.get_demo(st(request).pool, body.slug):
        raise HTTPException(409, "slug đã tồn tại")
    data = body.model_dump()
    data["embed_model"] = data.get("embed_model") or st(request).settings.gemini_embed_model
    d = await repo.create_demo(st(request).pool, data)
    await after_write(request, body.slug)
    return d


@router.get("/v1/admin/demos/{slug}")
async def get_demo(slug: str, request: Request):
    d = await demo_or_404(request, slug)
    idx = st(request).indexes.get(slug)
    d["index"] = None if idx is None else {"version": idx.version, "products": idx.n, "vectors": idx.n_vectors,
                                           "built_ms": round(idx.built_ms, 1), "thresholds": idx.thresholds,
                                           "scoring": idx.scoring}
    return d


@router.patch("/v1/admin/demos/{slug}")
async def patch_demo(slug: str, body: DemoPatch, request: Request):
    d = await demo_or_404(request, slug)
    out = await repo.update_demo(st(request).pool, d["id"], body.model_dump(exclude_none=True))
    await after_write(request, slug)
    return out


@router.delete("/v1/admin/demos/{slug}")
async def delete_demo(slug: str, request: Request):
    d = await demo_or_404(request, slug)
    await repo.delete_demo(st(request).pool, d["id"])
    st(request).indexes.drop(slug)
    return {"deleted": slug}


# ---------------------------------------------------------------- definitions
@router.get("/v1/admin/demos/{slug}/definitions")
async def get_defs(slug: str, request: Request):
    d = await demo_or_404(request, slug)
    return await repo.list_defs(st(request).pool, d["id"])


@router.put("/v1/admin/demos/{slug}/definitions")
async def put_defs(slug: str, body: list[AttributeDef], request: Request, replace: bool = False, reembed: bool = True):
    d = await demo_or_404(request, slug)
    async with st(request).pool.acquire() as conn, conn.transaction():
        await repo.upsert_defs(conn, d["id"], [x.model_dump() for x in body], replace=replace)
        v = await bump_version(conn, d["id"])
    await after_write(request, slug)
    job = await submit_embed(request, d["id"]) if reembed else None
    return {"data_version": v, "embed_job": job}


@router.delete("/v1/admin/demos/{slug}/definitions/{key}")
async def delete_def(slug: str, key: str, request: Request):
    d = await demo_or_404(request, slug)
    async with st(request).pool.acquire() as conn, conn.transaction():
        await repo.delete_def(conn, d["id"], key)
        v = await bump_version(conn, d["id"])
    await after_write(request, slug)
    return {"data_version": v}


# ---------------------------------------------------------------- products
@router.get("/v1/admin/demos/{slug}/products")
async def list_products(slug: str, request: Request):
    d = await demo_or_404(request, slug)
    return await repo.list_products(st(request).pool, d["id"])


@router.post("/v1/admin/demos/{slug}/products")
async def upsert_products(slug: str, body: list[ProductIn], request: Request, reembed: bool = True):
    d = await demo_or_404(request, slug)
    async with st(request).pool.acquire() as conn, conn.transaction():
        ids = await repo.upsert_products(conn, d["id"], [p.model_dump() for p in body])
        v = await bump_version(conn, d["id"])
    await after_write(request, slug)
    job = await submit_embed(request, d["id"]) if reembed else None
    return {"ids": ids, "data_version": v, "embed_job": job}


@router.get("/v1/admin/demos/{slug}/products/{pid}")
async def get_product(slug: str, pid: int, request: Request):
    d = await demo_or_404(request, slug)
    p = await repo.get_product(st(request).pool, d["id"], pid)
    if p is None:
        raise HTTPException(404, "không có sản phẩm")
    return p


@router.patch("/v1/admin/demos/{slug}/products/{pid}")
async def patch_product(slug: str, pid: int, body: ProductPatch, request: Request, reembed: bool = True):
    d = await demo_or_404(request, slug)
    async with st(request).pool.acquire() as conn, conn.transaction():
        p = await repo.patch_product(conn, d["id"], pid, body.model_dump(exclude_none=True))
        if p is None:
            raise HTTPException(404, "không có sản phẩm")
        v = await bump_version(conn, d["id"])
    await after_write(request, slug)
    job = await submit_embed(request, d["id"]) if reembed else None
    return {"product": p, "data_version": v, "embed_job": job}


@router.delete("/v1/admin/demos/{slug}/products/{pid}")
async def delete_product(slug: str, pid: int, request: Request):
    d = await demo_or_404(request, slug)
    async with st(request).pool.acquire() as conn, conn.transaction():
        await repo.delete_product(conn, d["id"], pid)
        v = await bump_version(conn, d["id"])
    await after_write(request, slug)
    return {"data_version": v}


# ---------------------------------------------------------------- import / template / embed
@router.post("/v1/admin/demos/{slug}/import")
async def import_file(slug: str, request: Request, file: UploadFile = File(...), dry_run: bool = Form(True),
                      mode: str = Form("upsert"), mapping: str | None = Form(None),
                      definitions: str | None = Form(None), reembed: bool = Form(True)):
    d = await demo_or_404(request, slug)
    if mode not in ("upsert", "replace"):
        raise HTTPException(422, "mode phải là upsert|replace")
    data = await file.read()
    try:
        plan = await plan_import(st(request).pool, d["id"], data, file.filename or "upload.csv",
                                 mapping=json.loads(mapping) if mapping else None,
                                 definitions=json.loads(definitions) if definitions else None)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"không đọc được file: {e}") from None
    if dry_run:
        return {"dry_run": True, "mapping": plan["mapping"], "columns": plan["columns"],
                "proposed_definitions": plan["proposed_definitions"], "n_rows": plan["n_rows"],
                "preview": plan["rows"][:10], "warnings": plan["warnings"]}
    if not plan["rows"]:
        raise HTTPException(422, {"message": "không có dòng hợp lệ", "warnings": plan["warnings"]})
    res = await apply_import(st(request).pool, d["id"], plan, mode=mode)
    await after_write(request, slug)
    res["embed_job"] = await submit_embed(request, d["id"]) if reembed else None
    res["warnings"] = plan["warnings"]
    return res


@router.get("/v1/admin/demos/{slug}/template.xlsx")
async def template(slug: str, request: Request, with_products: bool = False):
    d = await demo_or_404(request, slug)
    defs = await repo.list_defs(st(request).pool, d["id"])
    prods = await repo.list_products(st(request).pool, d["id"]) if with_products else None
    return Response(build_template(defs, prods),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{slug}_template.xlsx"'})


@router.post("/v1/admin/demos/{slug}/embed")
async def embed(slug: str, request: Request):
    d = await demo_or_404(request, slug)
    return {"job_id": await submit_embed(request, d["id"])}


# ---------------------------------------------------------------- enrich
@router.post("/v1/admin/demos/{slug}/enrich")
async def enrich(slug: str, body: EnrichRequest, request: Request):
    d = await demo_or_404(request, slug)
    s = st(request)

    async def job(ctx):
        res = await run_enrich(s.pool, s.gemini, d["id"], overwrite_fields=body.overwrite_fields,
                               product_ids=body.product_ids, timeout_ms=s.settings.offline_timeout_ms,
                               per_minute=s.settings.llm_offline_rpm, progress=ctx.progress)
        if not body.dry_run:
            res["applied"] = await apply_enrich(s.pool, d["id"], res["proposals"])
            await s.indexes.reload(slug)
            res["embed_job"] = await submit_embed(request, d["id"])
        return res

    return {"job_id": await s.jobs.submit("enrich", d["id"], body.model_dump(), job), "dry_run": body.dry_run}


@router.post("/v1/admin/demos/{slug}/enrich/{job_id}/apply")
async def enrich_apply(slug: str, job_id: str, body: EnrichApply, request: Request):
    d = await demo_or_404(request, slug)
    j = await repo.get_job(st(request).pool, job_id)
    if j is None or j["kind"] != "enrich" or j["status"] != "done":
        raise HTTPException(409, "job enrich chưa xong hoặc không tồn tại")
    res = await apply_enrich(st(request).pool, d["id"], j["result"]["proposals"], body.accept_product_ids,
                             body.edits, body.mark_reviewed)
    await after_write(request, slug)
    res["embed_job"] = await submit_embed(request, d["id"]) if body.reembed else None
    return res


# ---------------------------------------------------------------- eval cases
@router.get("/v1/admin/demos/{slug}/eval_cases")
async def list_eval(slug: str, request: Request, split: str = "all"):
    d = await demo_or_404(request, slug)
    return await repo.list_eval_cases(st(request).pool, d["id"], split, active_only=False)


@router.post("/v1/admin/demos/{slug}/eval_cases")
async def add_eval(slug: str, body: list[EvalCaseIn], request: Request):
    d = await demo_or_404(request, slug)
    rows = []
    for c in body:
        r = c.model_dump()
        r["context"] = c.context.model_dump() if c.context else None
        rows.append(r)
    return {"inserted": await repo.insert_eval_cases(st(request).pool, d["id"], rows)}


@router.delete("/v1/admin/demos/{slug}/eval_cases")
async def clear_eval(slug: str, request: Request, source: str | None = None):
    d = await demo_or_404(request, slug)
    await repo.delete_eval_cases(st(request).pool, d["id"], source)
    return {"ok": True}


@router.post("/v1/admin/demos/{slug}/eval_cases/generate")
async def gen_eval(slug: str, body: GenerateEvalRequest, request: Request):
    d = await demo_or_404(request, slug)
    s = st(request)

    async def job(ctx):
        res = await generate_cases(s.pool, s.gemini, s.search, slug, per_product=body.per_product,
                                   extra_general=body.extra_general, timeout_ms=s.settings.offline_timeout_ms,
                                   per_minute=s.settings.llm_offline_rpm, progress=ctx.progress)
        if not body.dry_run:
            res["inserted"] = await repo.insert_eval_cases(s.pool, d["id"], res["cases"])
        return res

    return {"job_id": await s.jobs.submit("gen_eval", d["id"], body.model_dump(), job)}


@router.post("/v1/admin/demos/{slug}/eval_cases/generate/{job_id}/apply")
async def gen_eval_apply(slug: str, job_id: str, request: Request, accept_indexes: list[int] | None = None):
    d = await demo_or_404(request, slug)
    j = await repo.get_job(st(request).pool, job_id)
    if j is None or j["kind"] != "gen_eval" or j["status"] != "done":
        raise HTTPException(409, "job chưa xong hoặc không tồn tại")
    cases = j["result"]["cases"]
    if accept_indexes is not None:
        cases = [c for i, c in enumerate(cases) if i in set(accept_indexes)]
    return {"inserted": await repo.insert_eval_cases(st(request).pool, d["id"], cases)}


# ---------------------------------------------------------------- evaluate / calibrate
@router.post("/v1/demos/{slug}/evaluate")
async def run_evaluate(slug: str, body: EvaluateRequest, request: Request):
    d = await demo_or_404(request, slug)
    s = st(request)

    async def job(ctx):
        return await evaluate(s.search, s.pool, slug, split=body.split, mode=body.mode, flags=body.flags,
                              concurrency=body.concurrency, progress=ctx.progress)

    job_id = await s.jobs.submit("evaluate", d["id"], body.model_dump(), job)
    if body.wait:
        await s.jobs.wait(job_id)
        return await repo.get_job(s.pool, job_id)
    return {"job_id": job_id}


@router.post("/v1/demos/{slug}/calibrate")
async def run_calibrate(slug: str, request: Request, save: bool = True, wait: bool = False, concurrency: int = 4):
    d = await demo_or_404(request, slug)
    s = st(request)

    async def job(ctx):
        res = await calibrate(s.search, s.pool, slug, concurrency=concurrency, save=save, progress=ctx.progress)
        await s.indexes.reload(slug)
        return res

    job_id = await s.jobs.submit("calibrate", d["id"], {"save": save}, job)
    if wait:
        await s.jobs.wait(job_id)
        return await repo.get_job(s.pool, job_id)
    return {"job_id": job_id}


# ---------------------------------------------------------------- jobs / logs / usage
@router.get("/v1/admin/jobs")
async def jobs(request: Request, demo: str | None = None):
    demo_id = (await demo_or_404(request, demo))["id"] if demo else None
    return await repo.list_jobs(st(request).pool, demo_id)


@router.get("/v1/admin/jobs/{job_id}")
async def job(job_id: str, request: Request):
    j = await repo.get_job(st(request).pool, job_id)
    if j is None:
        raise HTTPException(404, "không có job")
    return j


@router.get("/v1/admin/demos/{slug}/logs")
async def logs(slug: str, request: Request, limit: int = 50, wrong_only: bool = False):
    d = await demo_or_404(request, slug)
    q = "SELECT * FROM search_logs WHERE demo_id=$1"
    if wrong_only:
        q += " AND (feedback->>'correct')::bool = false"
    rows = await st(request).pool.fetch(q + " ORDER BY created_at DESC LIMIT $2", d["id"], min(limit, 500))
    return [dict(r) for r in rows]


@router.get("/v1/admin/usage")
async def usage(request: Request, days: int = 30):
    return {"live": st(request).gemini.usage.summary(), "db": await repo.usage_by_demo(st(request).pool, days)}
