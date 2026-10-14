"""Xác thực ID token của Google Sign-In qua endpoint tokeninfo (không cần client secret).
Trả về {sub, email, name, picture} nếu hợp lệ, None nếu không. Hàm verify được gắn vào app.state
để test thay bằng bản giả."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("auth.google")
TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


async def verify_google_token(credential: str, client_id: str, *, timeout_s: float = 5.0) -> dict | None:
    if not credential or not client_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as cx:
            r = await cx.get(TOKENINFO, params={"id_token": credential})
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("google tokeninfo failed: %s", e)
        return None
    if d.get("aud") != client_id or d.get("iss") not in ISSUERS:
        return None
    if str(d.get("email_verified", "")).lower() not in ("true", "1"):
        return None
    try:
        if int(d.get("exp", "0")) <= int(time.time()):
            return None
    except (TypeError, ValueError):
        return None
    sub, email = d.get("sub"), d.get("email")
    if not sub or not email:
        return None
    return {"sub": sub, "email": email, "name": d.get("name"), "picture": d.get("picture")}


def make_google_verifier(settings):
    async def verify(credential: str) -> dict | None:
        return await verify_google_token(credential, settings.google_client_id)

    return verify
