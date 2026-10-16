"""API "bảng dữ liệu" đơn giản cho tích hợp nhanh:
- tạo bảng từ Excel/CSV (xem trước -> tạo + embed),
- hỏi bằng câu tự nhiên -> trả về tối đa 5 dòng đúng tên cột gốc,
- thêm/cập nhật/xoá dòng theo đúng định dạng cột của file import đầu tiên.
Mỗi "bảng" là 1 demo; dùng chung pipeline search."""
from __future__ import annotations

import json
import re
import asyncpg

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

from fastapi import Header

from app import repo
from app.api.admin import after_write, demo_or_404, my_account_id, read_upload, st, submit_embed
from app.db import bump_version
from app.ingest.importer import apply_import, plan_import, rows_from_records, slug_key
from app.keys import SCOPES, KeyDecryptError, KeyNotSavedError
from app.search.pipeline import NotFound
from app.security import _match, require_principal

public = APIRouter()
admin = APIRouter(dependencies=[Depends(require_principal)])


def authorize(request: Request, slug: str, scope: str) -> None:
    """Cho phép khi: khoá quản trị đúng; (scope read) khoá API toàn cục đúng; hoặc khoá riêng của bảng đủ quyền.
    Nếu bảng chưa có khoá riêng nào và server không đặt khoá toàn cục -> mở (chế độ dev)."""
    s = request.app.state.settings
    ak = request.headers.get("x-api-key")
    adm = request.headers.get("x-admin-key")
    if _match(adm, s.admin_key_set):
        return
    # phiên đăng nhập (chủ bảng thao tác từ portal) hoặc super-admin
    from app.security import resolve_principal

    if resolve_principal(request) is not None:
        return
    if scope == "read" and _match(ak, s.api_key_set):
        return
    store = request.app.state.keys
    # khoá riêng của bảng gửi qua X-Table-Key hoặc dùng chung X-API-Key cho tiện
    if store.check(request.headers.get("x-table-key") or ak, slug, scope):
        return
    if not store.has_active(slug) and not s.admin_key_set and (scope != "read" or not s.api_key_set):
        return
    raise HTTPException(401, "cần khoá API hợp lệ cho bảng này" if store.has_active(slug) else "cần khoá API hợp lệ")


class AskBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=1, ge=1, le=5)
    mode: str = Field(default="auto", pattern="^(fast|auto|accurate)$")


class RowsBody(BaseModel):
    rows: list[dict] = Field(min_length=1, max_length=5000)
    mode: str = Field(default="upsert", pattern="^(upsert|replace)$")
    reembed: bool = True


class DeleteRowsBody(BaseModel):
    keys: list[str] = Field(min_length=1)


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default=["read"])
    expires_days: int | None = Field(default=None, ge=1, le=3650)


class KeyUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    scopes: list[str] | None = None
    active: bool | None = None
    expires_days: int | None = Field(default=None, ge=0, le=3650)


def _clean_scopes(scopes: list[str]) -> list[str]:
    out = [s for s in dict.fromkeys(scopes) if s in SCOPES]
    if not out:
        raise HTTPException(422, "scopes phải gồm 'read' và/hoặc 'write'")
    return out


def row_of(p: dict, columns: list[str] | None = None) -> dict:
    """Row trả về: nguyên dòng gốc nếu có (import Excel, giữ thứ tự cột của file), không thì dựng từ các trường."""
    if p.get("raw"):
        raw = p["raw"]
        if columns:
            return {**{c: raw.get(c) for c in columns if c in raw}, **{k: v for k, v in raw.items() if k not in columns}}
        return raw
    out = {k: p.get(k) for k in ("sku", "name", "category", "brand", "price", "price_unit", "in_stock",
                                 "short_description") if p.get(k) is not None}
    out.update(p.get("attributes") or {})
    out.update(p.get("extra") or {})
    return out


async def _ask(request: Request, slug: str, text: str, mode: str, top_k: int = 1) -> dict:
    svc = st(request).search
    try:
        # Giữ 3 ứng viên ở mặc định để alternatives và quyết định không đổi.
        r = await svc.search(slug, {"text": text, "top_k": max(3, top_k), "mode": mode})
    except NotFound:
        raise HTTPException(404, f"bảng '{slug}' không tồn tại") from None
    idx = st(request).indexes.get(slug)
    by_id = {p["id"]: p for p in idx.products} if idx else {}
    cols = (((idx.demo.get("settings") or {}).get("import") or {}).get("columns") if idx else None) or []
    top = r["products"][0] if r["products"] else None
    rows = [row_of(by_id[p["product_id"]], cols) for p in r["products"][:top_k]
            if p["product_id"] in by_id]
    return {
        "found": r["status"] == "matched",
        "status": r["status"],
        "row": row_of(by_id[top["product_id"]], cols) if top and top["product_id"] in by_id else None,
        "rows": rows,
        "count": len(rows),
        "score": top["score"] if top else 0.0,
        "row_key": top["sku"] if top else None,
        "clarify_question": r["clarify_question"],
        "alternatives": [{"row_key": p["sku"], "name": p["name"], "score": p["score"]} for p in r["products"][1:]],
        "request_id": r["request_id"],
        "latency_ms": r["latency_ms"]["total"],
    }


@public.post("/v1/tables/{slug}/ask")
async def ask(slug: str, body: AskBody, request: Request) -> dict:
    authorize(request, slug, "read")
    return await _ask(request, slug, body.text, body.mode, body.top_k)


@public.get("/v1/tables/{slug}/ask")
async def ask_get(slug: str, request: Request, text: str = Query(min_length=1, max_length=1000),
                  mode: str = Query(default="auto", pattern="^(fast|auto|accurate)$"),
                  top_k: int = Query(default=1, ge=1, le=5)) -> dict:
    authorize(request, slug, "read")
    return await _ask(request, slug, text, mode, top_k)


@admin.post("/v1/tables/{slug}/chat-context")
async def chat_context(slug: str, body: AskBody, request: Request) -> JSONResponse:
    """Owner-scoped, bounded lexical context for browser chat. Zero AI calls.

    Never expose raw imported columns or credentials to the external chat service.
    The browser sends these excerpts only after the user enables table context.
    """
    await demo_or_404(request, slug)
    try:
        result = await st(request).search.search(slug, {"text": body.text, "top_k": 3, "mode": "fast"}, flags={
            "understand": False, "embedding": False, "rerank": False,
            "embed_rewritten": False, "persistent_cache": False, "context": False,
        })
    except NotFound:
        raise HTTPException(409, "Bảng đang nạp dữ liệu; vui lòng thử lại.") from None
    rows = []
    for product in result["products"][:3]:
        row = {k: product.get(k) for k in ("product_id", "sku", "name", "price", "price_unit", "in_stock")}
        row["name"] = str(row.get("name") or "")[:240]
        row["sku"] = str(row.get("sku") or "")[:80]
        row["price_unit"] = str(row.get("price_unit") or "")[:40]
        row["attributes"] = [{"label": str(a.get("label") or "")[:60],
                              "value": str(a.get("display") or "")[:120]}
                             for a in product.get("attributes", [])[:6]]
        description = product.get("data", {}).get("short_description")
        if description:
            row["description"] = str(description)[:400]
        # Keep each complete record; never truncate serialized JSON mid-field.
        if len(json.dumps(rows + [row], ensure_ascii=False)) > 3000:
            break
        rows.append(row)
    return JSONResponse({"rows": rows, "data_version": result["data_version"], "retrieval": "lexical",
                         "external_ai_calls": 0}, headers={"Cache-Control": "no-store"})


@public.put("/v1/tables/{slug}/rows")
async def upsert_rows(slug: str, body: RowsBody, request: Request) -> dict:
    authorize(request, slug, "write")
    d = await demo_or_404(request, slug)
    cfg = (d.get("settings") or {}).get("import")
    if not cfg:
        raise HTTPException(409, "bảng chưa có cấu hình cột (cần import file Excel lần đầu)")
    defs = await repo.list_defs(st(request).pool, d["id"])
    rows, warns = rows_from_records(body.rows, cfg, defs)
    if not rows:
        raise HTTPException(422, {"message": "không có dòng hợp lệ", "warnings": warns})
    async with st(request).pool.acquire() as conn, conn.transaction():
        ids = await repo.upsert_products(conn, d["id"], rows, mode=body.mode)
        v = await bump_version(conn, d["id"])
    await after_write(request, slug)
    job = await submit_embed(request, d["id"]) if body.reembed else None
    return {"upserted": len(ids), "row_keys": list(ids), "data_version": v, "embed_job": job, "warnings": warns}


@public.delete("/v1/tables/{slug}/rows")
async def delete_rows(slug: str, body: DeleteRowsBody, request: Request) -> dict:
    authorize(request, slug, "write")
    d = await demo_or_404(request, slug)
    async with st(request).pool.acquire() as conn, conn.transaction():
        await repo.lock_demo(conn, d["id"])
        r = await conn.execute("DELETE FROM products WHERE demo_id=$1 AND sku = ANY($2::text[])", d["id"], body.keys)
        v = await bump_version(conn, d["id"])
    await after_write(request, slug)
    return {"deleted": int(r.split()[-1]), "data_version": v}


@admin.get("/v1/tables")
async def list_tables(request: Request) -> list[dict]:
    out = []
    for d in await repo.list_demos(st(request).pool, account_id=my_account_id(request)):
        idx = st(request).indexes.get(d["slug"])
        cfg = (d.get("settings") or {}).get("import") or {}
        out.append({"slug": d["slug"], "name": d["name"], "rows": d["n_products"], "eval_cases": d["n_eval"],
                    "vectors": idx.n_vectors if idx else 0, "data_version": d["data_version"],
                    "columns": cfg.get("columns") or [], "name_column": (cfg.get("mapping") or {}).get("name"),
                    "created_at": d["created_at"]})
    return out


@admin.get("/v1/tables/{slug}/rows")
async def list_rows(slug: str, request: Request, offset: int = 0, limit: int = 50, q: str | None = None) -> dict:
    d = await demo_or_404(request, slug)
    pool = st(request).pool
    where, args = "demo_id=$1", [d["id"]]
    if q:
        where += " AND (name ILIKE $2 OR sku ILIKE $2 OR raw::text ILIKE $2)"
        args.append(f"%{q}%")
    total = await pool.fetchval(f"SELECT count(*) FROM products WHERE {where}", *args)
    rows = await pool.fetch(f"SELECT id, sku, name, raw, attributes, extra, category, brand, price, price_unit, "
                            f"in_stock, short_description, updated_at FROM products WHERE {where} ORDER BY id "
                            f"OFFSET {max(0, offset)} LIMIT {max(1, min(limit, 500))}", *args)
    cols = ((d.get("settings") or {}).get("import") or {}).get("columns") or []
    return {"total": total, "rows": [{"row_key": r["sku"], "id": r["id"], "row": row_of(dict(r), cols),
                                      "updated_at": r["updated_at"]} for r in rows]}


def _slug_from_name(name: str) -> str:
    s = re.sub(r"_+", "-", slug_key(name))[:40].strip("-")
    return s if len(s) >= 2 else f"bang-{s}"


@admin.post("/v1/tables/preview")
async def preview_table(request: Request, file: UploadFile = File(...), mapping: str | None = Form(None)) -> dict:
    data = await read_upload(file)
    try:
        plan = await plan_import(st(request).pool, None, data, file.filename or "upload.xlsx",
                                 mapping=json.loads(mapping) if mapping else None)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"không đọc được file: {e}") from None
    return {"columns": plan["columns"], "mapping": plan["mapping"], "proposed_definitions": plan["proposed_definitions"],
            "n_rows": plan["n_rows"], "preview": [r["raw"] for r in plan["rows"][:10]], "warnings": plan["warnings"],
            "suggested_slug": _slug_from_name((file.filename or "bang").rsplit(".", 1)[0])}


@admin.post("/v1/tables", status_code=201)
async def create_table(request: Request, file: UploadFile = File(...), name: str = Form(...),
                       slug: str | None = Form(None), mapping: str | None = Form(None),
                       definitions: str | None = Form(None), industry: str | None = Form(None)) -> dict:
    s = st(request)
    slug = (slug or _slug_from_name(name)).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", slug):
        raise HTTPException(422, "slug chỉ gồm a-z, 0-9, -, _ (2-64 ký tự)")
    if await repo.get_demo(s.pool, slug):
        raise HTTPException(409, f"bảng '{slug}' đã tồn tại")
    data = await read_upload(file)
    try:
        plan = await plan_import(s.pool, None, data, file.filename or "upload.xlsx",
                                 mapping=json.loads(mapping) if mapping else None,
                                 definitions=json.loads(definitions) if definitions else None)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"không đọc được file: {e}") from None
    if not plan["rows"]:
        raise HTTPException(422, {"message": "không có dòng hợp lệ (cần cột tên)", "warnings": plan["warnings"]})
    try:
        async with s.pool.acquire() as conn, conn.transaction():
            d = await repo.create_demo(conn, {"slug": slug, "name": name, "industry": industry,
                                            "embed_model": s.settings.gemini_embed_model, "embed_dim": s.settings.embed_dim,
                                            "account_id": my_account_id(request)})
            res = await apply_import(s.pool, d["id"], plan, mode="replace", connection=conn)
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, f"bảng '{slug}' đã tồn tại") from None
    await after_write(request, slug)
    job = await submit_embed(request, d["id"])
    return {"slug": slug, "name": name, "rows": res["products"], "columns": plan["columns"],
            "embed_job": job, "warnings": plan["warnings"]}

# ---------------------------------------------------------------- khoá API theo bảng
def _key_out(k: dict) -> dict:
    return {"id": k["id"], "name": k["name"], "prefix": k["prefix"], "scopes": list(k["scopes"]),
            "active": k["active"], "expires_at": k["expires_at"], "created_at": k["created_at"],
            "last_used_at": k["last_used_at"], "use_count": k["use_count"],
            "can_reveal": k.get("can_reveal", False)}


@admin.get("/v1/tables/{slug}/keys")
async def list_keys(slug: str, request: Request) -> list[dict]:
    d = await demo_or_404(request, slug)
    return [_key_out(k) for k in await st(request).keys.list(d["id"])]


@admin.post("/v1/tables/{slug}/keys", status_code=201)
async def create_key(slug: str, body: KeyCreate, request: Request) -> JSONResponse:
    d = await demo_or_404(request, slug)
    raw, row = await st(request).keys.create(d["id"], body.name, _clean_scopes(body.scopes), body.expires_days)
    # Danh sách khóa luôn chỉ có metadata; khóa đầy đủ chỉ xuất ở create/reveal.
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(jsonable_encoder({"key": raw, **_key_out(row)}), status_code=201,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@admin.post("/v1/tables/{slug}/keys/{key_id}/reveal")
async def reveal_key(slug: str, key_id: int, request: Request) -> JSONResponse:
    d = await demo_or_404(request, slug)
    try:
        raw = await st(request).keys.reveal(d["id"], key_id)
    except KeyNotSavedError:
        return JSONResponse({"detail": "Không có bản lưu để xem lại. Khóa cũ vẫn dùng được; hãy tạo khóa mới nếu cần."},
                            status_code=409, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    except KeyDecryptError:
        return JSONResponse({"detail": "Không thể giải mã khóa. Kiểm tra cấu hình mã hóa của máy chủ."},
                            status_code=503, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    if raw is None:
        raise HTTPException(404, "không tìm thấy khóa")
    return JSONResponse({"id": key_id, "key": raw},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@admin.patch("/v1/tables/{slug}/keys/{key_id}")
async def update_key(slug: str, key_id: int, body: KeyUpdate, request: Request) -> dict:
    d = await demo_or_404(request, slug)
    data = body.model_dump(exclude_unset=True)
    if "scopes" in data and data["scopes"] is not None:
        data["scopes"] = _clean_scopes(data["scopes"])
    row = await st(request).keys.update(d["id"], key_id, data)
    if row is None:
        raise HTTPException(404, "không tìm thấy khoá")
    return _key_out(row)


@admin.delete("/v1/tables/{slug}/keys/{key_id}")
async def delete_key(slug: str, key_id: int, request: Request) -> dict:
    d = await demo_or_404(request, slug)
    if not await st(request).keys.delete(d["id"], key_id):
        raise HTTPException(404, "không tìm thấy khoá")
    return {"deleted": key_id}
