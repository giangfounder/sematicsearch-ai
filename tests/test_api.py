"""Tích hợp: Postgres thật (pgserver) + Gemini giả (không gọi API thật)."""
from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings, seed_demo, wait_job

CONTRACT = {"request_id", "status", "clarify_question", "products", "understanding", "relaxed", "relaxed_keys",
            "reranked", "cache_hit", "fallback_reason", "latency_ms"}
PRODUCT_KEYS = {"rank", "product_id", "sku", "name", "price", "price_unit", "in_stock", "score", "confidence",
                "reason", "attributes", "data"}


def search(c: TestClient, text: str, slug: str = "dm", **kw):
    r = c.post(f"/v1/demos/{slug}/search", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_contract_and_basic_match(client):
    ids = seed_demo(client)
    r = search(client, "dạ cho em hỏi sam sung 236 còn không ạ", debug=True)
    assert CONTRACT <= set(r)
    assert set(r["latency_ms"]) >= {"total", "understand", "embed", "retrieve", "rerank"}
    assert set(r["understanding"]) >= {"intent", "rewritten_query", "filters", "entities"}
    assert r["products"] and PRODUCT_KEYS <= set(r["products"][0])
    assert r["products"][0]["product_id"] == ids["TL1"]
    assert r["status"] == "matched"
    assert len(r["debug"]["candidates"]) <= 10
    for a in r["products"][0]["attributes"]:
        assert set(a) == {"key", "label", "value", "unit", "display"}
    assert "vec" not in str(r["products"][0]["data"])


def test_top_k_and_ambiguous_clarify(client):
    seed_demo(client)
    r = search(client, "tủ lạnh samsung", top_k=3, mode="fast")
    assert r["status"] in ("ambiguous", "matched")
    assert len(r["products"]) <= 3
    if r["status"] == "ambiguous":
        assert r["clarify_question"]
    r1 = search(client, "tủ lạnh samsung", top_k=1, mode="fast")
    assert len(r1["products"]) <= 1


def test_hard_filter_and_relax(client):
    ids = seed_demo(client)
    r = search(client, "tủ lạnh dưới 3 triệu", mode="fast", debug=True)
    assert r["products"][0]["product_id"] == ids["TL4"]
    assert not r["relaxed"]
    r = search(client, "tủ lạnh samsung dưới 3 triệu", mode="fast")
    assert r["relaxed"] and "brand" in r["relaxed_keys"]


def test_out_of_scope_and_chitchat(client):
    seed_demo(client)
    gem = client.app.state.gemini
    gem.handlers["understand"] = lambda **kw: {"intent": "out_of_scope", "rewritten_query": "", "mentioned_products": [],
                                               "filters": {"attributes": []}}
    r = search(client, "giá vàng hôm nay")
    assert r["status"] == "out_of_scope" and r["products"] == []
    # LLM nói out_of_scope nhưng câu có thực thể rõ -> vẫn tìm
    r = search(client, "tủ lạnh samsung 236 lít")
    assert r["status"] != "out_of_scope"
    # không có thực thể nhưng khớp rất mạnh với nhu cầu của 1 sản phẩm -> lưới an toàn ghi đè
    r = search(client, "sinh viên ở trọ", mode="fast")
    assert r["status"] != "out_of_scope" and r["understanding"]["intent_llm"] == "out_of_scope"


@pytest.mark.parametrize("fail,reason", [("understand", "understand_error"), ("embed_query", "embed_error")])
def test_fallback_when_gemini_fails(client, fail, reason):
    ids = seed_demo(client)
    gem = client.app.state.gemini
    gem.fail[fail] = "error"
    r = search(client, "sam sung 236 lít", mode="fast")
    assert reason in r["fallback_reason"]
    assert r["products"] and r["products"][0]["product_id"] == ids["TL1"]
    assert r["cache_hit"] is False
    r2 = search(client, "sam sung 236 lít", mode="fast")
    assert r2["cache_hit"] is False  # không cache kết quả fallback


def test_understand_timeout_fallback(db_url):
    from app.main import create_app

    app = create_app(make_settings(db_url, understand_timeout_ms=50))
    with TestClient(app) as c:
        ids = seed_demo(c)
        c.app.state.gemini.delay_ms["understand"] = 500
        t0 = time.perf_counter()
        r = search(c, "tủ lạnh dưới 3 triệu", mode="fast")
        assert (time.perf_counter() - t0) < 0.45
        assert "understand_timeout" in r["fallback_reason"]
        assert r["products"][0]["product_id"] == ids["TL4"]


def test_understand_soft_deadline(db_url):
    from app.main import create_app

    app = create_app(make_settings(db_url, understand_soft_deadline_ms=100))
    with TestClient(app) as c:
        ids = seed_demo(c)
        gem = c.app.state.gemini
        gem.delay_ms["understand"] = 400
        t0 = time.perf_counter()
        r = search(c, "tủ lạnh dưới 3 triệu", mode="fast")
        assert time.perf_counter() - t0 < 0.35
        assert "understand_deferred" in r["fallback_reason"]
        assert r["products"][0]["product_id"] == ids["TL4"]
        time.sleep(0.5)  # LLM chạy nền xong -> ghi cache understanding
        n = gem.calls["understand"]
        r2 = search(c, "tủ lạnh dưới 3 triệu", mode="fast")
        assert r2["fallback_reason"] is None and gem.calls["understand"] == n
        # có ngữ cảnh nhiều lượt thì vẫn chờ LLM
        r3 = search(c, "loại rẻ hơn", mode="fast", context={"previous_text": "tủ lạnh", "previous_product_ids": [ids["TL1"]]})
        assert "understand_deferred" not in (r3["fallback_reason"] or "")


def test_rerank_gating_modes(client):
    seed_demo(client)
    gem = client.app.state.gemini
    r = search(client, "tủ lạnh", mode="fast")
    assert r["reranked"] is False
    n0 = gem.calls.get("rerank", 0)
    r = search(client, "tủ lạnh", mode="accurate")
    assert r["reranked"] is True and gem.calls["rerank"] == n0 + 1
    gem.fail["rerank"] = "timeout"
    r = search(client, "tủ lạnh loại nào tốt", mode="accurate")
    assert r["reranked"] is False and "rerank_timeout" in r["fallback_reason"] and r["products"]


def test_response_cache_and_version_invalidation(client):
    ids = seed_demo(client)
    r1 = search(client, "tivi sony 55 inch", mode="fast")
    r2 = search(client, "tivi sony 55 inch", mode="fast")
    assert r2["cache_hit"] is True and r2["request_id"] != r1["request_id"]
    assert r2["latency_ms"]["total"] < 20
    # đổi dữ liệu -> data_version tăng -> cache vô hiệu, index mới có giá mới
    r = client.patch(f"/v1/admin/demos/dm/products/{ids['TV1']}?reembed=false", json={"price": 15000000})
    assert r.status_code == 200
    r3 = search(client, "tivi sony 55 inch", mode="fast")
    assert r3["cache_hit"] is False
    assert [p["price"] for p in r3["products"] if p["product_id"] == ids["TV1"]] == [15000000]


def test_notify_reload_from_other_writer(client, db_url):
    """Ghi thẳng DB (như 1 worker khác) -> NOTIFY -> listener nạp lại index."""
    import asyncio

    import asyncpg

    seed_demo(client)
    v0 = client.app.state.indexes.get("dm").version

    async def bump():
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow("UPDATE demos SET data_version=data_version+1 WHERE slug='dm' RETURNING data_version")
            await conn.execute("SELECT pg_notify('demo_changed', $1)", f"dm:{row['data_version']}")
        finally:
            await conn.close()

    asyncio.run(bump())
    for _ in range(100):
        if client.app.state.indexes.get("dm").version > v0:
            break
        time.sleep(0.05)
    assert client.app.state.indexes.get("dm").version == v0 + 1


def test_multi_turn_context(client):
    ids = seed_demo(client)
    gem = client.app.state.gemini
    gem.handlers["understand"] = lambda **kw: {
        "intent": "ask_detail", "rewritten_query": "tivi sony 55 inch bảo hành bao lâu", "mentioned_products": [],
        "filters": {"attributes": []}}
    r = search(client, "cái đó bảo hành bao lâu", mode="fast",
               context={"previous_text": "tivi sony 55 inch", "previous_product_ids": [ids["TV1"]]})
    assert r["products"][0]["product_id"] == ids["TV1"]
    assert r["understanding"]["intent"] == "ask_detail"


def test_refine_previous_merges_filters(client):
    ids = seed_demo(client)
    gem = client.app.state.gemini
    gem.handlers["understand"] = lambda **kw: {
        "intent": "refine_previous", "rewritten_query": "tủ lạnh samsung màu đen", "mentioned_products": [],
        "filters": {"attributes": [{"key": "mau", "op": "eq", "value_text": "Đen", "explicit": True}]}}
    r = search(client, "màu đen thì sao", mode="fast",
               context={"previous_text": "tủ lạnh samsung", "previous_product_ids": [ids["TL1"]],
                        "previous_filters": {"brand": "Samsung", "brand_explicit": True, "attributes": []}})
    assert r["products"][0]["product_id"] == ids["TL2"]  # Samsung + đen
    f = r["understanding"]["filters"]
    assert f["brand"] == "Samsung"


def test_auth(db_url):
    from app.main import create_app

    app = create_app(make_settings(db_url, api_keys="k1", admin_keys="adm"))
    with TestClient(app) as c:
        assert c.post("/v1/demos/x/search", json={"text": "a"}).status_code == 401
        assert c.post("/v1/demos/x/search", json={"text": "a"}, headers={"X-API-Key": "k1"}).status_code == 404
        assert c.get("/v1/admin/demos").status_code == 401
        assert c.get("/v1/admin/demos", headers={"X-API-Key": "k1"}).status_code == 401
        assert c.get("/v1/admin/demos", headers={"X-Admin-Key": "adm"}).status_code == 200
        h = c.get("/health?full=true").json()
        assert "gemini" not in h


def test_import_dry_run_and_apply(client):
    client.post("/v1/admin/demos", json={"slug": "imp", "name": "Import", "embed_dim": 64})
    csv = ("Mã SP,Tên sản phẩm,Hãng,Giá,Dung tích (lít),Màu,Có Inverter,Tên khác\n"
           "A1,Tủ lạnh Alpha 200 lít,Alpha,\"6.290.000\",200,Đen,có,alpha 200|tủ alpha\n"
           "A2,Tủ lạnh Beta 300 lít,Beta,8tr5,300,Bạc,không,\n"
           "A3,Tủ lạnh Gamma,Gamma,giá liên hệ,abc,Đen,có,\n"
           "A3,Trùng mã,Gamma,1000000,100,Đen,có,\n")
    files = {"file": ("sp.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}
    r = client.post("/v1/admin/demos/imp/import", files=files, data={"dry_run": "true"})
    assert r.status_code == 200, r.text
    j = r.json()
    defs = {d["key"]: d for d in j["proposed_definitions"]}
    assert defs["dung_tich"]["type"] == "number" and defs["dung_tich"]["unit"] == "lít"
    assert defs["mau"]["type"] == "enum" and defs["co_inverter"]["type"] == "bool"
    assert j["mapping"]["sku"] == "Mã SP" and j["mapping"]["price"] == "Giá"
    assert j["preview"][0]["price"] == 6290000 and j["preview"][1]["price"] == 8500000
    assert j["preview"][0]["aliases"] == ["alpha 200", "tủ alpha"]
    assert any("trùng SKU" in w for w in j["warnings"]) and any("giá không đọc được" in w for w in j["warnings"])
    assert client.get("/v1/admin/demos/imp/products").json() == []  # dry_run không ghi
    files = {"file": ("sp.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}
    r = client.post("/v1/admin/demos/imp/import", files=files, data={"dry_run": "false"})
    assert r.status_code == 200, r.text
    wait_job(client, r.json()["embed_job"])
    prods = client.get("/v1/admin/demos/imp/products").json()
    assert len(prods) == 3
    idx = client.app.state.indexes.get("imp")
    assert idx.n == 3 and idx.n_vectors > 0
    r = client.get("/v1/admin/demos/imp/template.xlsx?with_products=true")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_reembed_only_changed(client):
    ids = seed_demo(client)
    r = client.patch(f"/v1/admin/demos/dm/products/{ids['TV1']}", json={"aliases": ["sony năm lăm"]})
    j = wait_job(client, r.json()["embed_job"])
    res = j["result"]
    assert res["embedded"] == 1 and res["removed"] == 1 and res["reused"] > 10


def test_feedback_creates_eval_case(client):
    ids = seed_demo(client)
    r = search(client, "tủ lạnh nhỏ cho sinh viên", mode="fast")
    fb = client.post(f"/v1/search/{r['request_id']}/feedback",
                     json={"correct": False, "correct_product_id": ids["TL4"], "add_to_eval": True})
    assert fb.status_code == 200, fb.text
    assert fb.json()["eval_case"]["expected_product_ids"] == [ids["TL4"]]
    cases = client.get("/v1/admin/demos/dm/eval_cases").json()
    assert any(c["source"] == "log" for c in cases)
    assert client.post("/v1/search/khong-co/feedback", json={"correct": True}).status_code == 404


def test_evaluate_and_calibrate(client):
    ids = seed_demo(client)
    cases = []
    for i in range(6):
        for sku, q in [("TL1", "sam sung 236"), ("TL3", "lg 4 cánh"), ("TL4", "tủ mini"), ("TV2", "sony 65")]:
            cases.append({"query": f"{q} {'ạ' * (i % 2)} lần {i}", "expected_product_ids": [ids[sku]],
                          "expected_status": "matched", "category": "alias", "split": "dev" if i < 4 else "test"})
    cases.append({"query": "xe máy honda", "expected_product_ids": [], "expected_status": "no_match",
                  "category": "no_match", "split": "dev"})
    assert client.post("/v1/admin/demos/dm/eval_cases", json=cases).status_code == 200
    r = client.post("/v1/demos/dm/evaluate", json={"split": "test", "mode": "fast", "wait": True})
    rep = r.json()["result"]
    assert rep["n_cases"] == 8 and rep["hit@1"] is not None and "latency_ms" in rep
    assert set(rep) >= {"hit@1", "hit@3", "mrr", "status_accuracy", "matched_wrong_rate", "rerank_rate",
                        "confusion", "by_category", "failures", "suggestions"}
    r = client.post("/v1/demos/dm/calibrate?wait=true")
    j = r.json()
    assert j["status"] == "done", j
    th = j["result"]["thresholds"]
    assert th["t_min"] < th["t_match"]
    assert client.app.state.indexes.get("dm").thresholds["t_match"] == th["t_match"]


def test_health_full(client):
    seed_demo(client)
    search(client, "tivi sony")
    h = client.get("/health?full=true").json()
    assert h["status"] == "ok" and "dm" in h["demos"]
    assert "breakers" in h["gemini"] and "usage" in h["gemini"]
    assert h["cache"]["response"]["size"] >= 1
