"""X-API-Key cho search, X-Admin-Key cho quản trị; filter che key trong log."""
from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException, Request

from app.gemini.pool import redact


def _match(key: str | None, allowed: set[str]) -> bool:
    return bool(key) and any(hmac.compare_digest(key, k) for k in allowed)


async def require_api_key(request: Request, x_api_key: str | None = Header(default=None),
                          x_admin_key: str | None = Header(default=None)) -> None:
    s = request.app.state.settings
    allowed = s.api_key_set
    if not allowed:
        return
    if _match(x_api_key, allowed) or _match(x_admin_key, s.admin_key_set):
        return
    raise HTTPException(401, "invalid api key")


async def require_admin(request: Request, x_admin_key: str | None = Header(default=None)) -> None:
    s = request.app.state.settings
    allowed = s.admin_key_set
    if not allowed:
        return  # dev: không cấu hình ADMIN_KEYS = mở (README yêu cầu đặt khi deploy)
    if not _match(x_admin_key, allowed):
        raise HTTPException(401, "invalid admin key")


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization") or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def resolve_principal(request: Request) -> dict | None:
    """Ai đang gọi endpoint quản trị: phiên đăng nhập (account_id), hoặc khoá admin toàn cục (super),
    hoặc dev-mở (super) khi chưa đặt ADMIN_KEYS và chưa có tài khoản nào. None = chưa xác thực."""
    s = request.app.state.settings
    store = getattr(request.app.state, "accounts", None)
    sess = store.resolve(_bearer(request)) if store else None
    if sess:
        return {"account_id": sess["account_id"], "email": sess["email"], "name": sess.get("name"),
                "is_admin": sess["is_admin"], "super": False}
    if _match(request.headers.get("x-admin-key"), s.admin_key_set):
        return {"account_id": None, "email": None, "name": None, "is_admin": True, "super": True}
    if not s.admin_key_set and (store is None or not store.has_accounts):
        return {"account_id": None, "email": None, "name": None, "is_admin": True, "super": True}
    return None


async def require_principal(request: Request) -> dict:
    """Dependency cho endpoint quản trị: cần phiên đăng nhập hoặc khoá admin. Lưu vào request.state.principal."""
    p = resolve_principal(request)
    if p is None:
        raise HTTPException(401, "cần đăng nhập")
    request.state.principal = p
    return p


def principal_of(request: Request) -> dict | None:
    return getattr(request.state, "principal", None)


async def require_admin_account(request: Request) -> dict:
    """Chỉ tài khoản quản trị (is_admin) hoặc super-admin (khoá admin / dev) mới quản lý được tài khoản khác."""
    p = resolve_principal(request)
    if p is None:
        raise HTTPException(401, "cần đăng nhập")
    if not (p.get("super") or p.get("is_admin")):
        raise HTTPException(403, "cần quyền quản trị tài khoản")
    request.state.principal = p
    return p


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True
