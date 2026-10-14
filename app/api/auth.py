"""Đăng nhập / đăng xuất / thông tin tài khoản hiện tại."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.security import _bearer, require_principal

router = APIRouter()


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    remember: bool = False


class GoogleBody(BaseModel):
    credential: str = Field(min_length=10, max_length=8000)
    remember: bool = True


@router.get("/v1/auth/config")
async def auth_config(request: Request) -> dict:
    """Cấu hình công khai cho trang đăng nhập (client id Google để hiện nút)."""
    s = request.app.state.settings
    return {"google_client_id": s.google_client_id, "google_enabled": bool(s.google_client_id)}


@router.post("/v1/auth/login")
async def login(body: LoginBody, request: Request) -> dict:
    store = request.app.state.accounts
    res = await store.login(str(body.email), body.password, body.remember)
    if res is None:
        raise HTTPException(401, "Email hoặc mật khẩu không đúng")
    token, acc = res
    return {"token": token, "account": acc, "super": acc["is_admin"], "remember": body.remember}


@router.post("/v1/auth/google")
async def google_login(body: GoogleBody, request: Request) -> dict:
    s = request.app.state.settings
    if not s.google_client_id:
        raise HTTPException(400, "Đăng nhập Google chưa được cấu hình")
    info = await request.app.state.google_verify(body.credential)
    if not info:
        raise HTTPException(401, "Token Google không hợp lệ")
    res = await request.app.state.accounts.login_google(
        info["sub"], info["email"], info.get("name"), info.get("picture"),
        allow_signup=s.google_allow_signup, remember=body.remember)
    if res is None:
        raise HTTPException(403, "Tài khoản chưa được phép hoặc đã bị khoá")
    token, acc = res
    return {"token": token, "account": acc, "super": acc["is_admin"], "remember": body.remember}


@router.post("/v1/auth/logout")
async def logout(request: Request) -> dict:
    await request.app.state.accounts.logout(_bearer(request))
    return {"ok": True}


@router.get("/v1/auth/me")
async def me(request: Request, principal: dict = Depends(require_principal)) -> dict:
    store = request.app.state.accounts
    if principal["super"] and principal["account_id"] is None:
        return {"super": True, "account": None}
    acc = await store.get(principal["account_id"])
    if acc is None:
        raise HTTPException(401, "phiên không hợp lệ")
    return {"super": principal["super"], "account": store.public(acc)}
