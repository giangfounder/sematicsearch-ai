import numpy as np

from app.gemini.fake import hash_embed
from app.search import retrieve as R
from app.search.scoring import composite
from tests.conftest import make_index

FL = {"soft_filter": True, "relax": True, "multi_vector": True, "bm25": True, "entity": True, "float_rescore": True}


def run(idx, text, filters=None, ent=None, intent="find_product", ctx=None, flags=None):
    q = hash_embed(text, 64)
    ent = ent if ent is not None else idx.entity.match(text).products
    f = filters or {"price": None, "attributes": []}
    return R.retrieve(idx, qvec=q, texts=[text], filters=f, intent=intent, ctx=ctx, ent_products=ent,
                      flags={**FL, **(flags or {})})


def test_hard_filter_only_explicit():
    idx = make_index()
    f = {"price": {"max": 7e6, "explicit": True}, "attributes": [], "brand": "LG", "brand_explicit": False}
    rt = run(idx, "tủ lạnh", f)
    pids = {c["product_id"] for c in rt.candidates}
    assert pids <= {1, 4}  # chỉ giá <= 7tr; hãng LG chỉ là mềm
    assert not rt.relaxed_keys


def test_relax_lowest_weight_first():
    idx = make_index()
    f = {"price": {"max": 3e6, "explicit": True}, "brand": "Samsung", "brand_explicit": True, "attributes": []}
    rt = run(idx, "tủ lạnh samsung", f)
    assert rt.relaxed_keys == ["brand"]  # brand 0.85 < price 0.9
    assert {c["product_id"] for c in rt.candidates} == {4}


def test_baseline_makes_all_hard():
    idx = make_index()
    f = {"price": None, "brand": "LG", "brand_explicit": False, "attributes": []}
    rt = run(idx, "tủ lạnh", f, flags={"soft_filter": False, "relax": False})
    assert {c["product_id"] for c in rt.candidates} == {3}


def test_entity_and_rrf_rank_alias_first():
    idx = make_index()
    rt = run(idx, "sam sung 236")
    composite(idx, rt.candidates, has_dense=True, flags={})
    assert rt.candidates[0]["product_id"] == 1
    assert rt.candidates[0]["entity"] == 1.0


def test_ask_detail_restricts_to_previous():
    idx = make_index()
    rt = run(idx, "bảo hành bao lâu", intent="ask_detail", ctx={"previous_product_ids": [5]}, ent={})
    assert [c["product_id"] for c in rt.candidates] == [5]


def test_soft_score_price_approx():
    idx = make_index()
    f = {"price": {"approx": 8.5e6, "explicit": False}, "attributes": []}
    rt = run(idx, "tủ lạnh", f)
    soft = {c["product_id"]: c["soft"] for c in rt.candidates}
    assert soft[2] > soft[1] > soft[3]


def test_int8_close_to_float():
    idx = make_index()
    q = hash_embed("tủ lạnh samsung", 64)
    a, _ = R.dense_scores(idx, q, True, {0, 1, 2, 3})
    b, _ = R.dense_scores(idx, q, False, {0, 1, 2, 3})
    assert np.max(np.abs(a - b)) < 0.02
