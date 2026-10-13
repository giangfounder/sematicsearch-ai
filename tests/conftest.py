from __future__ import annotations

import os
import tempfile
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.catalog.index import build_index
from app.catalog.quant import quantize
from app.catalog.texts import vector_texts
from app.config import Settings
from app.gemini.fake import hash_embed

DEFS = [
    {"key": "dung_tich", "label": "Dung tích", "type": "number", "unit": "lít", "unit_aliases": ["l"],
     "filterable": True, "searchable": True, "weight": 0.6, "enum_values": [], "label_aliases": []},
    {"key": "so_cua", "label": "Số cửa", "type": "number", "unit": "cửa", "unit_aliases": ["cánh"],
     "filterable": True, "searchable": True, "weight": 0.7, "enum_values": [], "label_aliases": []},
    {"key": "inverter", "label": "Inverter", "type": "bool", "label_aliases": ["tiết kiệm điện"],
     "filterable": False, "searchable": True, "weight": 0.4, "enum_values": [], "unit_aliases": []},
    {"key": "man_hinh", "label": "Màn hình", "type": "number", "unit": "inch", "unit_aliases": ["in"],
     "filterable": True, "searchable": True, "weight": 0.8, "enum_values": [], "label_aliases": []},
    {"key": "mau", "label": "Màu", "type": "enum", "filterable": True, "searchable": True, "weight": 0.5,
     "enum_values": [{"value": "Đen", "aliases": ["màu đen"]}, {"value": "Bạc", "aliases": ["màu bạc", "xám bạc"]}],
     "label_aliases": [], "unit_aliases": []},
]

PRODUCTS = [
    {"sku": "TL1", "name": "Tủ lạnh Samsung Inverter 236 lít", "category": "Tủ lạnh", "brand": "Samsung", "price": 6290000,
     "attributes": {"dung_tich": 236, "so_cua": 2, "inverter": True, "mau": "Bạc"}, "aliases": ["sam sung 236"],
     "use_cases": ["gia đình 2-3 người"], "sample_questions": ["tủ lạnh samsung 236 lít giá bao nhiêu"]},
    {"sku": "TL2", "name": "Tủ lạnh Samsung Inverter 305 lít", "category": "Tủ lạnh", "brand": "Samsung", "price": 8490000,
     "attributes": {"dung_tich": 305, "so_cua": 2, "inverter": True, "mau": "Đen"}, "aliases": ["samsung 305"],
     "use_cases": ["gia đình 3-4 người"], "sample_questions": ["samsung 305 lít còn không"]},
    {"sku": "TL3", "name": "Tủ lạnh LG 4 cánh 500 lít", "category": "Tủ lạnh", "brand": "LG", "price": 19490000,
     "attributes": {"dung_tich": 500, "so_cua": 4, "inverter": True, "mau": "Đen"}, "aliases": ["lg 4 cánh"],
     "use_cases": ["gia đình đông người"], "sample_questions": ["tủ lạnh lg bốn cánh"]},
    {"sku": "TL4", "name": "Tủ lạnh mini Aqua 90 lít", "category": "Tủ lạnh", "brand": "Aqua", "price": 2890000,
     "attributes": {"dung_tich": 90, "so_cua": 1, "inverter": False}, "aliases": ["tủ mini"],
     "use_cases": ["sinh viên ở trọ"], "sample_questions": ["tủ lạnh nhỏ cho phòng trọ"]},
    {"sku": "TV1", "name": "Tivi Sony 55 inch", "category": "Tivi", "brand": "Sony", "price": 16490000,
     "attributes": {"man_hinh": 55}, "aliases": ["sô ni 55"], "use_cases": ["phòng khách"],
     "sample_questions": ["tivi sony 55 inch"]},
    {"sku": "TV2", "name": "Tivi Sony 65 inch", "category": "Tivi", "brand": "Sony", "price": 21990000, "in_stock": False,
     "attributes": {"man_hinh": 65}, "aliases": ["sony 65"], "use_cases": ["phòng khách rộng"],
     "sample_questions": ["tivi sony 65 inch"]},
]


# embedding giả (băm n-gram) cho cosine thấp hơn Gemini thật nhiều -> khoảng chuẩn hoá riêng
FAKE_SCORING = {"scoring": {"cos_lo": 0.0, "cos_hi": 0.6}}


def make_index(products=None, defs=None, thresholds=None, settings=None, with_vectors=True):
    products = [dict(p, id=i + 1, in_stock=p.get("in_stock", True)) for i, p in enumerate(products or PRODUCTS)]
    defs = defs or DEFS
    demo = {"id": 1, "slug": "t", "name": "Test", "industry": "điện máy", "data_version": 1,
            "embed_model": "fake", "embed_dim": 64, "thresholds": thresholds or {}, "settings": settings or FAKE_SCORING}
    vectors = []
    if with_vectors:
        for p in products:
            for kind, txt in vector_texts(p, defs):
                v = hash_embed(txt, 64)
                q, s = quantize(v[None, :])
                vectors.append({"product_id": p["id"], "kind": kind, "source_text": txt, "text_hash": "x",
                                "embed_model": "fake", "vec_int8": q[0].tobytes(), "scale": float(s[0]),
                                "vec_f32": v.astype(np.float32).tobytes()})
    return build_index(demo, defs, products, vectors)


@pytest.fixture(scope="session")
def pg_base():
    import pgserver

    d = tempfile.mkdtemp(prefix="semsearch_test_pg_")
    srv = pgserver.get_server(d, cleanup_mode="stop")
    yield srv
    srv.cleanup()


@pytest.fixture
def db_url(pg_base):
    name = "t_" + uuid.uuid4().hex[:10]
    pg_base.psql(f"CREATE DATABASE {name};")
    return pg_base.get_uri().rsplit("/", 1)[0] + "/" + name


def make_settings(db_url: str, **kw) -> Settings:
    base = dict(database_url=db_url, gemini_provider="fake", gemini_api_key="", embed_dim=64, api_keys="",
                admin_keys="", version_poll_s=0.5, embed_doc_rpm=10000, llm_offline_rpm=10000,
                gemini_embed_model="fake-embed", _env_file=None)
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def client(db_url):
    from app.main import create_app

    app = create_app(make_settings(db_url))
    with TestClient(app) as c:
        yield c


def seed_demo(client: TestClient, slug: str = "dm") -> dict:
    r = client.post("/v1/admin/demos", json={"slug": slug, "name": "Điện máy test", "industry": "điện máy", "embed_dim": 64,
                                                  "settings": FAKE_SCORING})
    assert r.status_code == 201, r.text
    r = client.put(f"/v1/admin/demos/{slug}/definitions?reembed=false", json=DEFS)
    assert r.status_code == 200, r.text
    r = client.post(f"/v1/admin/demos/{slug}/products?reembed=false", json=PRODUCTS)
    assert r.status_code == 200, r.text
    ids = r.json()["ids"]
    r = client.post(f"/v1/admin/demos/{slug}/embed")
    job = r.json()["job_id"]
    wait_job(client, job)
    return ids


def wait_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    import time

    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/v1/admin/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            assert j["status"] == "done", j
            return j
        time.sleep(0.05)
    raise TimeoutError(job_id)


os.environ.setdefault("PYTHONIOENCODING", "utf-8")
