"""Đăng nhập, phiên, và sở hữu bảng theo tài khoản."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import repo
from app.accounts import AccountStore, verify_password
from app.db import create_pool, migrate
from app.main import create_app
from tests.conftest import make_settings


def seeded(db_url):
    return create_app(make_settings(db_url, seed_account_email="a@x.com", seed_account_password="pw123456",
                                    seed_account_name="Chủ A", seed_account_phone="0123"))


def test_login_me_logout(db_url):
    with TestClient(seeded(db_url)) as c:
        assert c.post("/v1/auth/login", json={"email": "a@x.com", "password": "sai"}).status_code == 401
        r = c.post("/v1/auth/login", json={"email": "A@X.com", "password": "pw123456", "remember": True})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["account"]["email"] == "a@x.com" and j["account"]["name"] == "Chủ A" and j["super"] is True
        tok = j["token"]
        h = {"Authorization": f"Bearer {tok}"}
        me = c.get("/v1/auth/me", headers=h)
        assert me.status_code == 200 and me.json()["account"]["email"] == "a@x.com"
        assert c.get("/v1/auth/me").status_code == 401  # không token
        # đã có tài khoản -> endpoint quản trị bắt buộc đăng nhập
        assert c.get("/v1/tables").status_code == 401
        assert c.get("/v1/tables", headers=h).status_code == 200
        # token sai -> 401
        assert c.get("/v1/tables", headers={"Authorization": "Bearer khong-hop-le"}).status_code == 401
        c.post("/v1/auth/logout", headers=h)
        assert c.get("/v1/auth/me", headers=h).status_code == 401  # phiên đã huỷ


def test_seeded_account_owns_demos(db_url):
    """Tài khoản seed nhận các bảng chưa có chủ (dữ liệu mẫu) khi khởi động."""
    with TestClient(seeded(db_url)) as c:
        h = {"Authorization": f"Bearer {c.post('/v1/auth/login', json={'email': 'a@x.com', 'password': 'pw123456'}).json()['token']}"}
        # tạo 1 bảng qua demo API -> thuộc tài khoản
        assert c.post("/v1/admin/demos", json={"slug": "t1", "name": "T1", "embed_dim": 64}, headers=h).status_code == 201
        tables = c.get("/v1/tables", headers=h).json()
        assert "t1" in {t["slug"] for t in tables}


async def test_account_scoping_and_password(db_url):
    pool = await create_pool(db_url)
    await migrate(pool)
    store = AccountStore(pool)
    await store.load_sessions()
    a = await store.ensure_account("a@x.com", "pw123456", name="A")
    b = await store.ensure_account("b@x.com", "pw999999", name="B")
    assert store.has_accounts
    await repo.create_demo(pool, {"slug": "ta", "name": "TA", "account_id": a["id"]})
    await repo.create_demo(pool, {"slug": "tb", "name": "TB", "account_id": b["id"]})
    await repo.create_demo(pool, {"slug": "shared", "name": "S", "account_id": None})
    la = {d["slug"] for d in await repo.list_demos(pool, account_id=a["id"])}
    assert la == {"ta", "shared"} and "tb" not in la  # A thấy bảng của mình + bảng chung, không thấy của B
    alld = {d["slug"] for d in await repo.list_demos(pool)}  # super-admin thấy hết
    assert alld == {"ta", "tb", "shared"}
    # mật khẩu băm, không lưu thô
    assert a["pass_hash"] != "pw123456" and len(a["pass_salt"]) >= 16
    assert verify_password("pw123456", a["pass_salt"], a["pass_hash"])
    assert not verify_password("sai", a["pass_salt"], a["pass_hash"])
    # phiên
    res = await store.login("A@X.com", "pw123456", False)
    assert res is not None
    tok, acc = res
    assert acc["email"] == "a@x.com" and store.resolve(tok)["account_id"] == a["id"]
    assert store.resolve("linh tinh") is None
    await store.logout(tok)
    assert store.resolve(tok) is None
    await pool.close()


def test_cross_account_cannot_access_table(db_url):
    """Tài khoản B không thấy/sửa được bảng của A qua HTTP."""
    with TestClient(seeded(db_url)) as c:
        # seed account A; tạo thêm B qua store của app (cùng loop qua một request giả lập không có -> dùng login A tạo bảng)
        ha = {"Authorization": f"Bearer {c.post('/v1/auth/login', json={'email': 'a@x.com', 'password': 'pw123456'}).json()['token']}"}
        c.post("/v1/admin/demos", json={"slug": "rieng-a", "name": "Riêng A", "embed_dim": 64}, headers=ha)
        # tạo tài khoản B trực tiếp rồi đăng nhập
        import anyio
        anyio.from_thread  # noqa: B018
        acc_b = c.portal.call(c.app.state.accounts.ensure_account, "b@x.com", "pw999999")  # type: ignore[attr-defined]
        hb = {"Authorization": f"Bearer {c.post('/v1/auth/login', json={'email': 'b@x.com', 'password': 'pw999999'}).json()['token']}"}
        assert "rieng-a" not in {t["slug"] for t in c.get("/v1/tables", headers=hb).json()}
        assert c.get("/v1/admin/demos/rieng-a", headers=hb).status_code == 404  # B không thấy bảng của A
        assert c.get("/v1/admin/demos/rieng-a", headers=ha).status_code == 200  # A thấy


def test_account_management_by_admin(db_url):
    """Admin (tài khoản seed is_admin) tạo/sửa/xoá tài khoản khác; chặn tự khoá."""
    with TestClient(seeded(db_url)) as c:  # seed account a@x.com là is_admin
        ha = {"Authorization": f"Bearer {c.post('/v1/auth/login', json={'email': 'a@x.com', 'password': 'pw123456'}).json()['token']}"}
        # tạo tài khoản thường
        r = c.post("/v1/admin/accounts", json={"email": "u1@x.com", "password": "pass12", "name": "User 1"}, headers=ha)
        assert r.status_code == 201, r.text
        uid = r.json()["id"]
        assert r.json()["is_admin"] is False and r.json()["email"] == "u1@x.com"
        # trùng email -> 409
        assert c.post("/v1/admin/accounts", json={"email": "u1@x.com", "password": "pass12"}, headers=ha).status_code == 409
        # liệt kê
        emails = {a["email"] for a in c.get("/v1/admin/accounts", headers=ha).json()}
        assert {"a@x.com", "u1@x.com"} <= emails
        # sửa: đổi tên + đặt làm admin
        r = c.patch(f"/v1/admin/accounts/{uid}", json={"name": "User Một", "is_admin": True}, headers=ha)
        assert r.json()["name"] == "User Một" and r.json()["is_admin"] is True
        # đặt lại mật khẩu -> đăng nhập bằng mật khẩu mới
        c.patch(f"/v1/admin/accounts/{uid}", json={"password": "newpass1"}, headers=ha)
        assert c.post("/v1/auth/login", json={"email": "u1@x.com", "password": "newpass1"}).status_code == 200
        assert c.post("/v1/auth/login", json={"email": "u1@x.com", "password": "pass12"}).status_code == 401
        # admin không tự bỏ quyền của mình
        me = c.get("/v1/auth/me", headers=ha).json()["account"]["id"]
        assert c.patch(f"/v1/admin/accounts/{me}", json={"is_admin": False}, headers=ha).status_code == 400
        # xoá tài khoản khác
        assert c.delete(f"/v1/admin/accounts/{uid}", headers=ha).json()["deleted"] == uid
        assert "u1@x.com" not in {a["email"] for a in c.get("/v1/admin/accounts", headers=ha).json()}
        # không tự xoá mình
        assert c.delete(f"/v1/admin/accounts/{me}", headers=ha).status_code == 400


def _fake_verify(mapping):
    async def verify(credential):
        return mapping.get(credential)
    return verify


def test_google_login_signup_and_admin_manage(db_url):
    """Đăng nhập Google: lần đầu tạo tài khoản mới (non-admin), admin thấy và quản lý được."""
    app = create_app(make_settings(db_url, seed_account_email="a@x.com", seed_account_password="pw123456",
                                   seed_account_name="Chủ A",
                                   google_client_id="test-client.apps.googleusercontent.com"))
    with TestClient(app) as c:
        c.app.state.google_verify = _fake_verify({  # type: ignore[attr-defined]
            "credential-newuser-001": {"sub": "g-1", "email": "newuser@gmail.com", "name": "New User", "picture": "http://p/a.png"}})
        # config công khai lộ client id để frontend hiện nút
        assert c.get("/v1/auth/config").json()["google_enabled"] is True
        # token Google không hợp lệ -> 401
        assert c.post("/v1/auth/google", json={"credential": "khong-biet"}).status_code == 401
        # đăng nhập lần đầu = đăng ký
        r = c.post("/v1/auth/google", json={"credential": "credential-newuser-001"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["account"]["email"] == "newuser@gmail.com" and j["account"]["is_admin"] is False
        assert j["account"]["via_google"] is True and j["super"] is False
        tok = j["token"]
        assert c.get("/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
        # đăng nhập lại cùng Google -> cùng tài khoản, không tạo trùng
        r2 = c.post("/v1/auth/google", json={"credential": "credential-newuser-001"})
        assert r2.json()["account"]["id"] == j["account"]["id"]
        # admin thấy tài khoản Google và quản lý được
        ha = {"Authorization": f"Bearer {c.post('/v1/auth/login', json={'email': 'a@x.com', 'password': 'pw123456'}).json()['token']}"}
        accs = {a["email"]: a for a in c.get("/v1/admin/accounts", headers=ha).json()}
        assert "newuser@gmail.com" in accs and accs["newuser@gmail.com"]["via_google"] is True
        uid = accs["newuser@gmail.com"]["id"]
        # admin khoá tài khoản Google -> không đăng nhập Google được nữa
        assert c.patch(f"/v1/admin/accounts/{uid}", json={"active": False}, headers=ha).status_code == 200
        assert c.post("/v1/auth/google", json={"credential": "credential-newuser-001"}).status_code == 403


def test_google_links_existing_email_account(db_url):
    """Đăng nhập Google bằng email trùng tài khoản sẵn có -> liên kết, giữ nguyên quyền admin."""
    app = create_app(make_settings(db_url, seed_account_email="a@x.com", seed_account_password="pw123456",
                                   google_client_id="test-client.apps.googleusercontent.com"))
    with TestClient(app) as c:
        c.app.state.google_verify = _fake_verify({  # type: ignore[attr-defined]
            "credential-aaccount-001": {"sub": "g-a", "email": "a@x.com", "name": "A G", "picture": None}})
        r = c.post("/v1/auth/google", json={"credential": "credential-aaccount-001"})
        assert r.status_code == 200
        assert r.json()["account"]["is_admin"] is True and r.json()["super"] is True  # vẫn là admin seed
        # mật khẩu cũ vẫn dùng được
        assert c.post("/v1/auth/login", json={"email": "a@x.com", "password": "pw123456"}).status_code == 200


def test_google_signup_disabled(db_url):
    """Tắt google_allow_signup: email lạ không tạo được tài khoản."""
    app = create_app(make_settings(db_url, seed_account_email="a@x.com", seed_account_password="pw123456",
                                   google_client_id="test-client.apps.googleusercontent.com",
                                   google_allow_signup=False))
    with TestClient(app) as c:
        c.app.state.google_verify = _fake_verify({  # type: ignore[attr-defined]
            "credential-stranger-1": {"sub": "g-x", "email": "stranger@gmail.com", "name": "X", "picture": None}})
        assert c.post("/v1/auth/google", json={"credential": "credential-stranger-1"}).status_code == 403


def test_non_admin_cannot_manage_accounts(db_url):
    with TestClient(seeded(db_url)) as c:
        ha = {"Authorization": f"Bearer {c.post('/v1/auth/login', json={'email': 'a@x.com', 'password': 'pw123456'}).json()['token']}"}
        c.post("/v1/admin/accounts", json={"email": "normal@x.com", "password": "pass12", "name": "N"}, headers=ha)
        hn = {"Authorization": f"Bearer {c.post('/v1/auth/login', json={'email': 'normal@x.com', 'password': 'pass12'}).json()['token']}"}
        assert c.get("/v1/admin/accounts", headers=hn).status_code == 403  # tài khoản thường -> cấm
        assert c.post("/v1/admin/accounts", json={"email": "x2@x.com", "password": "pass12"}, headers=hn).status_code == 403
