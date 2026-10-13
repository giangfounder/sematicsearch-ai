from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app import repo
from app.schemas import FeedbackRequest, SearchRequest
from app.search.pipeline import NotFound
from app.security import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/v1/demos/{slug}/search")
async def search(slug: str, body: SearchRequest, request: Request) -> dict:
    svc = request.app.state.search
    req = body.model_dump()
    if body.context is not None:
        req["context"] = body.context.model_dump()
    try:
        return await svc.search(slug, req)
    except NotFound:
        raise HTTPException(404, f"demo '{slug}' không tồn tại hoặc chưa nạp") from None


@router.get("/v1/demos")
async def list_public_demos(request: Request) -> list[dict]:
    return [{"slug": i.slug, "name": i.demo["name"], "industry": i.demo.get("industry"), "products": i.n,
             "vectors": i.n_vectors, "data_version": i.version}
            for i in request.app.state.indexes.indexes.values()]


@router.post("/v1/search/{request_id}/feedback")
async def feedback(request_id: str, body: FeedbackRequest, request: Request) -> dict:
    pool = request.app.state.pool
    await request.app.state.logs.flush_now()
    row = await repo.get_log(pool, request_id)
    if row is None:
        raise HTTPException(404, "request_id không tồn tại")
    fb = {"correct": body.correct, "correct_product_id": body.correct_product_id}
    await repo.set_feedback(pool, request_id, fb)
    created = None
    if body.add_to_eval:
        und = row.get("understanding") or {}
        if body.correct:
            expected = (row.get("product_ids") or [])[:1]
            status = row["status"]
        else:
            expected = [body.correct_product_id] if body.correct_product_id else []
            status = "matched" if expected else ("out_of_scope" if und.get("intent") in ("out_of_scope", "chitchat") else "no_match")
        await repo.insert_eval_cases(pool, row["demo_id"], [{
            "query": row["text"], "context": row.get("context"), "expected_product_ids": expected,
            "expected_status": status, "category": "from_log", "split": body.split, "source": "log"}])
        created = {"expected_product_ids": expected, "expected_status": status}
    return {"ok": True, "eval_case": created}
