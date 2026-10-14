"""Tài khoản + phiên đăng nhập. Mật khẩu băm PBKDF2-HMAC-SHA256 (stdlib, chạy được ARM, không cần lib ngoài);
token phiên chỉ lưu bản băm SHA-256. Phiên tra trong RAM (làm mới định kỳ) để không query DB mỗi request."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

log = logging.getLogger("accounts")
PBKDF2_ITERS = 210_000
SESSION_DAYS = 1
SESSION_DAYS_REMEMBER = 30


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERS)
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, got = hash_password(password, salt)
    return hmac.compare_digest(got, expected_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _acc_public(a: dict) -> dict:
    return {"id": a["id"], "email": a["email"], "name": a.get("name"), "phone": a.get("phone"),
            "is_admin": a["is_admin"], "created_at": a.get("created_at")}


class AccountStore:
    def __init__(self, pool):
        self.pool = pool
        self.sessions: dict[str, dict] = {}  # token_hash -> {account_id, email, name, is_admin, expires_at}
        self.has_accounts = False  # còn tài khoản nào không -> quyết định chế độ dev-mở
        self.task: asyncio.Task | None = None

    async def load_sessions(self) -> None:
        self.has_accounts = bool(await self.pool.fetchval("SELECT EXISTS(SELECT 1 FROM accounts)"))
        rows = await self.pool.fetch(
            """SELECT s.token_hash, s.account_id, s.expires_at, a.email, a.name, a.is_admin, a.active
               FROM sessions s JOIN accounts a ON a.id=s.account_id
               WHERE s.expires_at > now() AND a.active""")
        self.sessions = {r["token_hash"]: dict(r) for r in rows}

    async def start(self, refresh_s: float = 60.0) -> None:
        await self.load_sessions()
        self.task = asyncio.create_task(self._loop(refresh_s))

    async def _loop(self, refresh_s: float) -> None:
        while True:
            await asyncio.sleep(refresh_s)
            try:
                await self.pool.execute("DELETE FROM sessions WHERE expires_at <= now()")
                await self.load_sessions()
            except Exception:  # noqa: BLE001
                log.exception("session refresh failed")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()

    # ---------- tài khoản ----------
    async def get_by_email(self, email: str) -> dict | None:
        r = await self.pool.fetchrow("SELECT * FROM accounts WHERE email=$1", norm_email(email))
        return dict(r) if r else None

    async def get(self, account_id: int) -> dict | None:
        r = await self.pool.fetchrow("SELECT * FROM accounts WHERE id=$1", account_id)
        return dict(r) if r else None

    async def ensure_account(self, email: str, password: str, name: str | None = None, phone: str | None = None,
                             is_admin: bool = False) -> dict:
        """Tạo tài khoản nếu chưa có (dùng để seed). Không đổi mật khẩu tài khoản đã tồn tại."""
        existing = await self.get_by_email(email)
        if existing:
            return existing
        salt, h = hash_password(password)
        r = await self.pool.fetchrow(
            """INSERT INTO accounts(email, name, phone, pass_salt, pass_hash, is_admin)
               VALUES($1,$2,$3,$4,$5,$6) RETURNING *""",
            norm_email(email), name, phone, salt, h, is_admin)
        self.has_accounts = True
        log.info("created account %s", norm_email(email))
        return dict(r)

    # ---------- phiên ----------
    async def login(self, email: str, password: str, remember: bool) -> tuple[str, dict] | None:
        acc = await self.get_by_email(email)
        if acc is None or not acc["active"] or not verify_password(password, acc["pass_salt"], acc["pass_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        th = hash_token(token)
        exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS_REMEMBER if remember else SESSION_DAYS)
        await self.pool.execute(
            "INSERT INTO sessions(token_hash, account_id, remember, expires_at) VALUES($1,$2,$3,$4)",
            th, acc["id"], remember, exp)
        self.sessions[th] = {"token_hash": th, "account_id": acc["id"], "email": acc["email"],
                             "name": acc["name"], "is_admin": acc["is_admin"], "expires_at": exp}
        return token, _acc_public(acc)

    def resolve(self, token: str | None) -> dict | None:
        """Trả thông tin tài khoản từ token phiên (RAM), None nếu không hợp lệ/hết hạn."""
        if not token:
            return None
        s = self.sessions.get(hash_token(token))
        if s is None:
            return None
        if s["expires_at"] <= datetime.now(timezone.utc):
            self.sessions.pop(s["token_hash"], None)
            return None
        return s

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        th = hash_token(token)
        self.sessions.pop(th, None)
        await self.pool.execute("DELETE FROM sessions WHERE token_hash=$1", th)

    async def touch(self, token: str) -> None:
        await self.pool.execute("UPDATE sessions SET last_seen_at=now() WHERE token_hash=$1", hash_token(token))

    def public(self, acc: dict) -> dict:
        return _acc_public(acc)

    # ---------- quản trị tài khoản ----------
    async def list_accounts(self) -> list[dict]:
        rows = await self.pool.fetch(
            """SELECT a.id, a.email, a.name, a.phone, a.is_admin, a.active, a.created_at,
                      (SELECT count(*) FROM demos d WHERE d.account_id=a.id) AS n_tables
               FROM accounts a ORDER BY a.id""")
        return [dict(r) for r in rows]

    async def create_account(self, email: str, password: str, name: str | None, phone: str | None,
                             is_admin: bool) -> dict:
        if await self.get_by_email(email):
            raise ValueError("email đã tồn tại")
        salt, h = hash_password(password)
        r = await self.pool.fetchrow(
            """INSERT INTO accounts(email, name, phone, pass_salt, pass_hash, is_admin)
               VALUES($1,$2,$3,$4,$5,$6) RETURNING *""",
            norm_email(email), name, phone, salt, h, is_admin)
        self.has_accounts = True
        return dict(r)

    async def count_active_admins(self) -> int:
        return await self.pool.fetchval("SELECT count(*) FROM accounts WHERE is_admin AND active")

    async def update_account(self, account_id: int, data: dict) -> dict | None:
        sets, args = [], [account_id]
        for col in ("name", "phone", "is_admin", "active"):
            if col in data and data[col] is not None:
                args.append(data[col])
                sets.append(f"{col}=${len(args)}")
        drop_sessions = False
        if data.get("password"):
            salt, h = hash_password(data["password"])
            args += [salt, h]
            sets += [f"pass_salt=${len(args) - 1}", f"pass_hash=${len(args)}"]
            drop_sessions = True
        if data.get("active") is False:
            drop_sessions = True
        if not sets:
            return await self.get(account_id)
        row = await self.pool.fetchrow(f"UPDATE accounts SET {', '.join(sets)} WHERE id=$1 RETURNING *", *args)
        if row and drop_sessions:  # đổi mật khẩu / khoá tài khoản -> huỷ mọi phiên của tài khoản đó
            await self.pool.execute("DELETE FROM sessions WHERE account_id=$1", account_id)
        await self.load_sessions()
        return dict(row) if row else None

    async def delete_account(self, account_id: int) -> bool:
        r = await self.pool.execute("DELETE FROM accounts WHERE id=$1", account_id)
        await self.load_sessions()
        return r.endswith("1")
