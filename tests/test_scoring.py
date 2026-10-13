from app.search.rerank import parse_rerank
from app.search.scoring import apply_rerank, clarify_question, decide, need_rerank
from tests.conftest import make_index


def C(i, score, pid=None):
    return {"i": i, "product_id": pid or i + 1, "score": score, "final": score}


def test_gating():
    idx = make_index()
    th = idx.thresholds
    assert need_rerank(idx, [C(0, 0.95), C(1, 0.5)], "auto", None, {})[0] is False
    assert need_rerank(idx, [C(0, 0.6), C(1, 0.55)], "auto", None, {})[0] is True
    assert need_rerank(idx, [C(0, 0.6), C(1, 0.55)], "auto", 1, {})[1] == "entity_exact"
    assert need_rerank(idx, [C(0, 0.99)], "accurate", None, {})[0] is True
    assert need_rerank(idx, [C(0, 0.1)], "fast", None, {})[0] is False
    assert th["gate_high"] > th["t_match"]


def test_decide_statuses():
    idx = make_index()
    assert decide(idx, [C(0, 0.9), C(1, 0.4)], None)[0] == "matched"
    st, close = decide(idx, [C(0, 0.75), C(1, 0.72), C(2, 0.2)], None)
    assert st == "ambiguous" and len(close) == 2
    assert decide(idx, [C(0, 0.75), C(1, 0.72)], 1)[0] == "matched"  # entity exact phá hoà
    assert decide(idx, [C(0, 0.2)], None)[0] == "no_match"
    assert decide(idx, [], None)[0] == "no_match"
    st, close = decide(idx, [C(0, 0.5)], None)
    assert st == "ambiguous" and len(close) == 1


def test_clarify_uses_distinguishing_attribute():
    idx = make_index()
    q = clarify_question(idx, [C(1, 0.7), C(2, 0.7)])  # Samsung 305 (2 cửa) vs LG 4 cánh
    assert "2 cửa" in q and "4 cửa" in q
    q1 = clarify_question(idx, [C(0, 0.5)])
    assert q1.startswith("Có phải") and "236" in q1


def test_rerank_parse_and_apply():
    idx = make_index()
    res = parse_rerank({"results": [{"product_id": 2, "relevance": 1.7, "satisfies_constraints": True, "reason": "ok"},
                                    {"product_id": 99, "relevance": 1, "satisfies_constraints": True, "reason": "x"},
                                    {"product_id": 1, "relevance": 0.9, "satisfies_constraints": False, "reason": "y"},
                                    {"product_id": 2, "relevance": 0, "satisfies_constraints": True, "reason": "dup"}]},
                       {1, 2, 3})
    assert set(res) == {1, 2} and res[2]["relevance"] == 1.0
    cands = [C(0, 0.6), C(1, 0.55), C(2, 0.5)]
    apply_rerank(idx, cands, res)
    assert cands[0]["product_id"] == 2 and cands[0]["reason"] == "ok"
    p1 = [c for c in cands if c["product_id"] == 1][0]
    assert p1["rerank_sat"] is False
