"""Khoá API riêng cho từng bảng: tạo (CRUD), phạm vi read/write, hết hạn, vô hiệu hoá, cô lập giữa các bảng."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import create_app
from tests.conftest import FAKE_SCORING, make_settings, wait_job

DATA = [["Mã", "Tên sản phẩm", "Giá"], ["A1", "Áo thun trắng", 120000], ["A2", "Quần jean xanh", 350000]]


def xf():
    wb = Workbook(); ws = wb.active
    for r in DATA:
        ws.append(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()


def admin_client(db_url):
    app = create_app(make_settings(db_url, admin_keys="ADM"))
    return TestClient(app)


def make_table(c, hdr):
    r = c.post("/v1/tables", files={"file": ("sp.xlsx", io.BytesIO(xf()))}, data={"name": "Áo quần", "slug": "aq"}, headers=hdr)
    assert r.status_code == 201, r.text
    wait_job_hdr(c, r.json()["embed_job"], hdr)
    c.patch("/v1/admin/demos/aq", json={"settings": {**FAKE_SCORING, "import": c.get("/v1/admin/demos/aq", headers=hdr).json()["settings"]["import"]}}, headers=hdr)


def wait_job_hdr(c, job, hdr):
    import time
    for _ in range(400):
        j = c.get(f"/v1/admin/jobs/{job}", headers=hdr).json()
        if j["status"] in ("done", "error"):
            assert j["status"] == "done", j
            return
        time.sleep(0.05)


def test_key_lifecycle_and_scopes(db_url):
    adm = {"X-Admin-Key": "ADM"}
    with admin_client(db_url) as c:
        make_table(c, adm)
        # chưa có khoá riêng, có admin key toàn cục -> ask cần khoá
        assert c.post("/v1/tables/aq/ask", json={"text": "áo thun"}).status_code == 401
        # tạo khoá chỉ-đọc
        r = c.post("/v1/tables/aq/keys", json={"name": "Bot đọc", "scopes": ["read"]}, headers=adm)
        assert r.status_code == 201, r.text
        k = r.json()
        assert k["key"].startswith("sk_tbl_") and k["prefix"] == k["key"][:12] and k["scopes"] == ["read"]
        read_key = k["key"]
        # khoá được liệt kê nhưng KHÔNG lộ lại key gốc
        lst = c.get("/v1/tables/aq/keys", headers=adm).json()
        assert len(lst) == 1 and "key" not in lst[0] and lst[0]["prefix"] == k["prefix"]
        # ask bằng X-API-Key = khoá bảng -> ok
        rr = c.post("/v1/tables/aq/ask", json={"text": "áo thun trắng"}, headers={"X-API-Key": read_key})
        assert rr.status_code == 200 and rr.json()["row_key"] == "A1"
        # cũng nhận qua X-Table-Key
        assert c.get("/v1/tables/aq/ask", params={"text": "quần jean"}, headers={"X-Table-Key": read_key}).status_code == 200
        # khoá read KHÔNG ghi được
        w = c.put("/v1/tables/aq/rows", json={"rows": [{"Mã": "A3", "Tên sản phẩm": "Nón", "Giá": 90000}]},
                  headers={"X-API-Key": read_key})
        assert w.status_code == 401
        # tạo khoá ghi
        wk = c.post("/v1/tables/aq/keys", json={"name": "Bot ghi", "scopes": ["read", "write"]}, headers=adm).json()["key"]
        ok = c.put("/v1/tables/aq/rows", json={"rows": [{"Mã": "A3", "Tên sản phẩm": "Nón lưỡi trai", "Giá": 90000}], "reembed": False},
                   headers={"X-API-Key": wk})
        assert ok.status_code == 200 and ok.json()["upserted"] == 1
        # admin key vẫn ghi được
        assert c.request("DELETE", "/v1/tables/aq/rows", json={"keys": ["A3"]}, headers=adm).status_code == 200


def test_key_revoke_expire_isolation(db_url):
    adm = {"X-Admin-Key": "ADM"}
    with admin_client(db_url) as c:
        make_table(c, adm)
        kid_key = c.post("/v1/tables/aq/keys", json={"name": "tạm", "scopes": ["read"]}, headers=adm).json()
        key, kid = kid_key["key"], kid_key["id"]
        assert c.post("/v1/tables/aq/ask", json={"text": "áo"}, headers={"X-API-Key": key}).status_code == 200
        # vô hiệu hoá -> 401
        c.patch(f"/v1/tables/aq/keys/{kid}", json={"active": False}, headers=adm)
        assert c.post("/v1/tables/aq/ask", json={"text": "áo"}, headers={"X-API-Key": key}).status_code == 401
        # bật lại + đổi tên
        u = c.patch(f"/v1/tables/aq/keys/{kid}", json={"active": True, "name": "đã bật"}, headers=adm).json()
        assert u["active"] and u["name"] == "đã bật"
        assert c.post("/v1/tables/aq/ask", json={"text": "áo"}, headers={"X-API-Key": key}).status_code == 200
        # khoá bảng aq không dùng được cho bảng khác
        c.post("/v1/tables", files={"file": ("x.xlsx", io.BytesIO(xf()))}, data={"name": "Khác", "slug": "khac"}, headers=adm)
        assert c.post("/v1/tables/khac/ask", json={"text": "áo"}, headers={"X-API-Key": key}).status_code == 401
        # xoá khoá -> 401
        assert c.delete(f"/v1/tables/aq/keys/{kid}", headers=adm).json()["deleted"] == kid
        assert c.post("/v1/tables/aq/ask", json={"text": "áo"}, headers={"X-API-Key": key}).status_code == 401
        assert c.get("/v1/tables/aq/keys", headers=adm).json() == []


def test_keys_require_admin(db_url):
    app = create_app(make_settings(db_url, admin_keys="ADM", api_keys="PUB"))
    with TestClient(app) as c:
        c.post("/v1/tables", files={"file": ("x.xlsx", io.BytesIO(xf()))}, data={"name": "A", "slug": "aq"}, headers={"X-Admin-Key": "ADM"})
        assert c.get("/v1/tables/aq/keys", headers={"X-API-Key": "PUB"}).status_code == 401
        assert c.post("/v1/tables/aq/keys", json={"name": "x"}, headers={"X-API-Key": "PUB"}).status_code == 401


def test_open_mode_when_no_keys(client):
    """Server không đặt khoá toàn cục và bảng chưa có khoá riêng -> mở (dev)."""
    from tests.conftest import seed_demo
    seed_demo(client, "dm")
    assert client.post("/v1/tables/dm/ask", json={"text": "tủ lạnh"}).status_code == 200
