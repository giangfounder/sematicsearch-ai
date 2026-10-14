"""Quản lý tài khoản (chỉ tài khoản quản trị): tạo, xem, sửa, xoá tài khoản khác."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.security import require_admin_account

router = APIRouter(dependencies=[Depends(require_admin_account)])


class AccountCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    is_admin: bool = False


class AccountUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    is_admin: bool | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=200)


def _store(request: Request):
    return request.app.state.accounts


def _out(a: dict) -> dict:
    return {"id": a["id"], "email": a["email"], "name": a.get("name"), "phone": a.get("phone"),
            "is_admin": a["is_admin"], "active": a["active"], "created_at": a.get("created_at"),
            "n_tables": a.get("n_tables", 0)}


def _me_id(request: Request) -> int | None:
    p = getattr(request.state, "principal", None)
    return p.get("account_id") if p else None


@router.get("/v1/admin/accounts")
async def list_accounts(request: Request) -> list[dict]:
    return [_out(a) for a in await _store(request).list_accounts()]


@router.post("/v1/admin/accounts", status_code=201)
async def create_account(body: AccountCreate, request: Request) -> dict:
    try:
        acc = await _store(request).create_account(body.email, body.password, body.name, body.phone, body.is_admin)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return _out(acc)


@router.patch("/v1/admin/accounts/{account_id}")
async def update_account(account_id: int, body: AccountUpdate, request: Request) -> dict:
    store = _store(request)
    acc = await store.get(account_id)
    if acc is None:
        raise HTTPException(404, "không tìm thấy tài khoản")
    data = body.model_dump(exclude_unset=True)
    # chống tự khoá chính mình ra khỏi quyền quản trị / vô hiệu hoá admin cuối cùng
    removing_admin = (data.get("is_admin") is False or data.get("active") is False) and acc["is_admin"] and acc["active"]
    if removing_admin and await store.count_active_admins() <= 1:
        raise HTTPException(400, "không thể bỏ quyền/khoá admin cuối cùng")
    if account_id == _me_id(request) and data.get("is_admin") is False:
        raise HTTPException(400, "không thể tự bỏ quyền quản trị của chính mình")
    out = await store.update_account(account_id, data)
    return _out(out)


@router.delete("/v1/admin/accounts/{account_id}")
async def delete_account(account_id: int, request: Request) -> dict:
    store = _store(request)
    acc = await store.get(account_id)
    if acc is None:
        raise HTTPException(404, "không tìm thấy tài khoản")
    if account_id == _me_id(request):
        raise HTTPException(400, "không thể tự xoá tài khoản của mình")
    if acc["is_admin"] and acc["active"] and await store.count_active_admins() <= 1:
        raise HTTPException(400, "không thể xoá admin cuối cùng")
    await store.delete_account(account_id)
    return {"deleted": account_id}
