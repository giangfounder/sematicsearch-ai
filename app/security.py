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


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True
