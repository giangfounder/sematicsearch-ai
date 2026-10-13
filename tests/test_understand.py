from app.search.rules import parse_rules
from app.search.understand import merge_filters, scale_price, validate_llm
from tests.conftest import make_index


def test_validate_drops_unknown_and_bad_types():
    idx = make_index()
    raw = {"intent": "find_product", "rewritten_query": "tủ lạnh samsung", "mentioned_products": [],
           "filters": {"brand": "samsung", "category": "Máy bay", "price": {"max": 10, "explicit": True},
                       "attributes": [
                           {"key": "khong_ton_tai", "op": "eq", "value_text": "x", "explicit": True},
                           {"key": "dung_tich", "op": "gte", "value_num": None, "value_text": "abc", "explicit": True},
                           {"key": "mau", "op": "eq", "value_text": "tím", "explicit": True},
                           {"key": "mau", "op": "eq", "value_text": "màu đen", "explicit": True},
                           {"key": "so_cua", "op": "eq", "value_num": 2, "explicit": True},
                           {"key": "inverter", "op": "eq", "value_text": "có", "explicit": True}]}}
    v = validate_llm(raw, idx)
    f = v["filters"]
    assert f["brand"] == "Samsung" and f["category"] is None
    assert f["price"]["max"] == 10e6  # 10 -> 10 triệu theo trung vị giá
    keys = [(a["key"], a["value"]) for a in f["attributes"]]
    assert ("mau", "Đen") in keys and ("so_cua", 2.0) in keys and ("inverter", True) in keys
    assert not any(k == "khong_ton_tai" for k, _ in keys)
    assert {"attr:khong_ton_tai", "attr:dung_tich:type", "attr:mau:enum", "category:Máy bay"} <= set(v["dropped"])
    inv = [a for a in f["attributes"] if a["key"] == "inverter"][0]
    assert inv["explicit"] is False  # không filterable -> chỉ mềm


def test_invalid_intent_defaults():
    idx = make_index()
    assert validate_llm({"intent": "hack"}, idx)["intent"] == "find_product"
    assert validate_llm("not a dict", idx)["intent"] == "find_product"


def test_scale_price():
    idx = make_index()
    assert scale_price(10, idx) == 10e6
    assert scale_price(9500000, idx) == 9500000


def test_rule_wins_on_price_and_numbers():
    idx = make_index()
    ent = idx.entity.match("tu lanh duoi 7 trieu 2 canh")
    rules = parse_rules("tủ lạnh dưới 7 triệu 2 cánh", idx.defs, ent, idx.units)
    llm = validate_llm({"intent": "find_product", "rewritten_query": "", "mentioned_products": [],
                        "filters": {"price": {"max": 9000000, "explicit": True},
                                    "attributes": [{"key": "so_cua", "op": "eq", "value_num": 4, "explicit": True}]}}, idx)
    f = merge_filters(llm, rules, ent.brands, ent.categories, idx)
    assert f["price"]["max"] == 7e6
    assert [a["value"] for a in f["attributes"] if a["key"] == "so_cua"] == [2.0]


def test_brand_only_from_llm_is_soft():
    idx = make_index()
    llm = validate_llm({"intent": "find_product", "rewritten_query": "", "mentioned_products": [],
                        "filters": {"brand": "LG", "attributes": []}}, idx)
    f = merge_filters(llm, {"price": None, "attributes": []}, [], [], idx)
    assert f["brand"] == "LG" and f["brand_explicit"] is False
