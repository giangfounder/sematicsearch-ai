"""API bảng dữ liệu: import, ask trả các dòng gốc, CRUD và quản lý bảng."""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from tests.conftest import FAKE_SCORING, wait_job


def xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


DATA = [
    ["Mã", "Tên sản phẩm", "Hãng", "Giá", "Dung tích (lít)", "Ghi chú"],
    ["TL01", "Tủ lạnh Samsung 236 lít", "Samsung", 6290000, 236, "bán chạy"],
    ["TL02", "Tủ lạnh LG 4 cánh 500 lít", "LG", 19490000, 500, None],
    ["MG01", "Máy giặt Toshiba lồng đứng 10 kg", "Toshiba", 6990000, None, "giặt chăn"],
]


def files(content: bytes, name: str = "sanpham.xlsx"):
    return {"file": (name, io.BytesIO(content), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def make_table(client, slug="sp"):
    r = client.post("/v1/tables", files=files(xlsx(DATA)), data={"name": "Sản phẩm test", "slug": slug})
    assert r.status_code == 201, r.text
    j = r.json()
    wait_job(client, j["embed_job"])
    # embedding giả cần khoảng cosine riêng (giống test khác)
    client.patch(f"/v1/admin/demos/{slug}", json={"settings": {**FAKE_SCORING, "import": _cfg(client, slug)}})
    return j


def _cfg(client, slug):
    return client.get(f"/v1/admin/demos/{slug}").json()["settings"]["import"]


def test_preview_does_not_write(client):
    r = client.post("/v1/tables/preview", files=files(xlsx(DATA)))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["mapping"]["name"] == "Tên sản phẩm" and j["mapping"]["sku"] == "Mã"
    assert j["n_rows"] == 3 and j["preview"][0]["Ghi chú"] == "bán chạy"
    assert j["suggested_slug"] == "sanpham"
    assert client.get("/v1/tables").json() == []


def test_create_ask_returns_original_row(client):
    j = make_table(client)
    assert j["rows"] == 3 and j["slug"] == "sp"
    r = client.post("/v1/tables/sp/ask", json={"text": "dạ cho hỏi tủ lạnh sam sung 236 lít"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert set(a) >= {"found", "status", "row", "score", "row_key", "clarify_question", "alternatives", "latency_ms"}
    assert a["row_key"] == "TL01"
    assert a["row"] == {"Mã": "TL01", "Tên sản phẩm": "Tủ lạnh Samsung 236 lít", "Hãng": "Samsung", "Giá": 6290000,
                        "Dung tích (lít)": 236, "Ghi chú": "bán chạy"}
    assert list(a["row"]) == DATA[0]  # giữ đúng thứ tự cột của file
    assert a["rows"] == [a["row"]] and a["count"] == 1
    g = client.get("/v1/tables/sp/ask", params={"text": "máy giặt lồng đứng"}).json()
    assert g["row_key"] == "MG01"
    assert client.post("/v1/tables/khong-co/ask", json={"text": "x"}).status_code == 404


def test_ask_top_k_returns_ranked_original_rows(client):
    data = [DATA[0]] + [
        [f"TL{i:02}", f"Tủ lạnh Samsung {200 + i * 20} lít", "Samsung", 6000000 + i * 100000,
         200 + i * 20, f"Mẫu {i}"] for i in range(1, 7)
    ]
    created = client.post("/v1/tables", files=files(xlsx(data)), data={"name": "Nhiều dòng", "slug": "nhieu"})
    assert created.status_code == 201, created.text
    wait_job(client, created.json()["embed_job"])
    # Đảm bảo các dòng cùng loại vượt ngưỡng, kiểm tra giới hạn thay vì độ chính xác embedding giả.
    patched = client.patch("/v1/admin/demos/nhieu", json={
        "settings": {**FAKE_SCORING, "import": _cfg(client, "nhieu")}, "thresholds": {"t_min": 0.0},
    })
    assert patched.status_code == 200, patched.text
    replies = []
    for top_k in (1, 3, 5):
        response = client.post("/v1/tables/nhieu/ask", json={"text": "tủ lạnh", "top_k": top_k, "mode": "fast"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["count"] == len(result["rows"]) == top_k
        assert result["row"] == result["rows"][0]
        assert result["row_key"] == result["rows"][0]["Mã"]
        assert all(list(row) == data[0] for row in result["rows"])
        originals = {row[0]: dict(zip(data[0], row)) for row in data[1:]}
        assert all(row == originals[row["Mã"]] for row in result["rows"])
        replies.append(result)
    assert replies[0]["rows"] == replies[2]["rows"][:1]
    assert replies[1]["rows"] == replies[2]["rows"][:3]
    assert len(replies[0]["alternatives"]) == 2  # không thay đổi mặc định của tích hợp cũ
    get_response = client.get("/v1/tables/nhieu/ask", params={"text": "tủ lạnh", "top_k": 2, "mode": "fast"})
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["rows"] == replies[2]["rows"][:2]
    assert get_response.json()["count"] == 2


def test_ask_top_k_can_return_fewer_rows_and_no_results(client, monkeypatch):
    make_table(client)
    response = client.post("/v1/tables/sp/ask", json={"text": "tủ lạnh", "top_k": 5, "mode": "fast"})
    assert response.status_code == 200, response.text
    assert 0 < response.json()["count"] <= 3
    assert response.json()["count"] == len(response.json()["rows"])

    async def no_results(slug, body):
        return {"products": [], "status": "no_match", "clarify_question": None,
                "request_id": "no-results", "latency_ms": {"total": 1.0}}

    monkeypatch.setattr(client.app.state.search, "search", no_results)
    empty = client.post("/v1/tables/sp/ask", json={"text": "không có", "top_k": 5}).json()
    assert empty["rows"] == [] and empty["count"] == 0
    assert empty["row"] is None and empty["found"] is False


@pytest.mark.parametrize("top_k", [0, -1, 6, 100, 1.5, "abc"])
def test_ask_rejects_invalid_top_k(client, top_k):
    assert client.post("/v1/tables/sp/ask", json={"text": "tủ lạnh", "top_k": top_k}).status_code == 422
    assert client.get("/v1/tables/sp/ask", params={"text": "tủ lạnh", "top_k": top_k}).status_code == 422


def test_ask_get_validates_mode(client):
    assert client.get("/v1/tables/sp/ask", params={"text": "tủ lạnh", "mode": "invalid"}).status_code == 422


def test_upsert_and_delete_rows_same_columns(client):
    make_table(client)
    r = client.put("/v1/tables/sp/rows", json={"rows": [
        {"Mã": "TL01", "Tên sản phẩm": "Tủ lạnh Samsung 236 lít", "Hãng": "Samsung", "Giá": 5990000, "Dung tích (lít)": 236},
        {"Mã": "DH01", "Tên sản phẩm": "Điều hòa Daikin 1 ngựa", "Hãng": "Daikin", "Giá": 10490000},
    ]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["upserted"] == 2 and set(j["row_keys"]) == {"TL01", "DH01"}
    wait_job(client, j["embed_job"])
    rows = {x["row_key"]: x["row"] for x in client.get("/v1/tables/sp/rows").json()["rows"]}
    assert rows["TL01"]["Giá"] == 5990000 and "DH01" in rows and len(rows) == 4
    a = client.post("/v1/tables/sp/ask", json={"text": "điều hòa daikin"}).json()
    assert a["row_key"] == "DH01"
    r = client.request("DELETE", "/v1/tables/sp/rows", json={"keys": ["DH01", "KHONG_CO"]})
    assert r.json()["deleted"] == 1
    assert client.get("/v1/tables/sp/rows").json()["total"] == 3
    bad = client.put("/v1/tables/sp/rows", json={"rows": [{"Ten": "x"}]})
    assert bad.status_code == 422


def test_table_management(client):
    make_table(client, "bang1")
    t = client.get("/v1/tables").json()
    assert t[0]["slug"] == "bang1" and t[0]["rows"] == 3 and t[0]["name_column"] == "Tên sản phẩm"
    assert "Ghi chú" in t[0]["columns"]
    assert client.patch("/v1/admin/demos/bang1", json={"name": "Đổi tên"}).status_code == 200
    assert client.get("/v1/tables").json()[0]["name"] == "Đổi tên"
    assert client.get("/v1/tables/bang1/rows", params={"q": "toshiba"}).json()["total"] == 1
    dup = client.post("/v1/tables", files=files(xlsx(DATA)), data={"name": "x", "slug": "bang1"})
    assert dup.status_code == 409
    assert client.delete("/v1/admin/demos/bang1").status_code == 200
    assert client.get("/v1/tables").json() == []
    assert client.post("/v1/tables/bang1/ask", json={"text": "tủ lạnh"}).status_code == 404


def test_no_key_column_generates_stable_keys(client):
    data = [["Tên", "Mô tả"], ["Gói A", "x"], ["Gói A", "trùng tên"], ["Gói B", "y"]]
    r = client.post("/v1/tables", files=files(xlsx(data), "goi.xlsx"), data={"name": "Gói"})
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "goi" and r.json()["rows"] == 3
    keys = sorted(x["row_key"] for x in client.get("/v1/tables/goi/rows").json()["rows"])
    assert keys == ["goi_a", "goi_a-2", "goi_b"]


def test_rows_api_requires_admin(db_url):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings

    app = create_app(make_settings(db_url, api_keys="k", admin_keys="adm"))
    with TestClient(app) as c:
        assert c.put("/v1/tables/x/rows", json={"rows": [{"a": 1}]}, headers={"X-API-Key": "k"}).status_code == 401
        assert c.get("/v1/tables", headers={"X-API-Key": "k"}).status_code == 401
        assert c.post("/v1/tables/x/ask", json={"text": "a"}, headers={"X-API-Key": "k"}).status_code == 404


def test_auto_mapping_prefix_and_unit_headers():
    from app.ingest.importer import auto_mapping

    m = auto_mapping(["Mã gói", "Tên gói", "Giá (đồng/tháng)", "Data (GB/ngày)"])
    assert m == {"sku": "Mã gói", "name": "Tên gói", "price": "Giá (đồng/tháng)"}


def test_recreate_same_slug_reloads_vectors(client):
    """Xoá rồi tạo lại bảng cùng slug: version đếm lại từ đầu, index vẫn phải nạp vector mới qua NOTIFY."""
    import time

    for _ in range(2):
        client.delete("/v1/admin/demos/lap")
        r = client.post("/v1/tables", files=files(xlsx(DATA)), data={"name": "Lặp", "slug": "lap"})
        wait_job(client, r.json()["embed_job"])
        for _ in range(100):
            idx = client.app.state.indexes.get("lap")
            if idx and idx.n_vectors > 0:
                break
            time.sleep(0.05)
        assert client.app.state.indexes.get("lap").n_vectors > 0
