import pytest

from app.search.rules import parse_money, parse_rules
from tests.conftest import make_index


@pytest.mark.parametrize("text,exp", [
    ("tủ lạnh dưới 10 triệu", {"max": 10e6}),
    ("tủ lạnh tầm 10 củ", {"approx": 10e6}),
    ("trên 5 triệu", {"min": 5e6}),
    ("từ 5 đến 7 triệu", {"min": 5e6, "max": 7e6}),
    ("2-3 triệu", {"min": 2e6, "max": 3e6}),
    ("9 triệu rưỡi", {"approx": 9.5e6}),
    ("8 triệu 9", {"approx": 8.9e6}),
    ("1 tỷ 2", {"approx": 1.2e9}),
    ("gói 120 nghìn", {"approx": 120e3}),
    ("50k trở xuống", {"max": 50e3}),
    ("giá 9.890.000", {"approx": 9.89e6}),
])
def test_money(text, exp):
    p = parse_money(text)
    for k, v in exp.items():
        assert p[k] == pytest.approx(v), (text, p)
    assert p["explicit"] is True


def test_money_sort():
    assert parse_money("máy giặt rẻ nhất")["sort"] == "asc"
    assert parse_money("điện thoại đắt nhất")["sort"] == "desc"
    p = parse_money("tủ lạnh giá rẻ")
    assert p["sort"] == "asc" and p["explicit"] is False


def test_attributes_units_and_enum():
    idx = make_index()
    ent = idx.entity.match("tu lanh mau den 2 canh")
    f = parse_rules("tủ lạnh màu đen hai cánh trên 300 lít", idx.defs, ent, idx.units)
    attrs = {a["key"]: a for a in f["attributes"]}
    assert attrs["so_cua"]["value"] == 2 and attrs["so_cua"]["op"] == "eq"
    assert attrs["dung_tich"]["op"] == "gte" and attrs["dung_tich"]["value"] == 300
    assert attrs["mau"]["value"] == "Đen" and attrs["mau"]["explicit"]


def test_bool_preference_is_soft():
    idx = make_index()
    f = parse_rules("tủ lạnh tiết kiệm điện", idx.defs, None, idx.units)
    a = [x for x in f["attributes"] if x["key"] == "inverter"][0]
    assert a["value"] is True and a["explicit"] is False


def test_brand_category_from_entities():
    idx = make_index()
    ent = idx.entity.match("tu lanh samsung")
    f = parse_rules("tủ lạnh samsung", idx.defs, ent, idx.units)
    assert f["brand"] == "Samsung" and f["brand_explicit"]
    assert f["category"] == "Tủ lạnh"
