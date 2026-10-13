from tests.conftest import make_index


def test_exact_alias_unique():
    idx = make_index()
    r = idx.entity.match("cho hoi sam sung 236 con khong")
    assert r.exact_unique == 1
    assert r.products[1]["match"] == "exact"


def test_fuzzy_name():
    idx = make_index()
    r = idx.entity.match("tu lanh mini aqa 90 lit")
    assert 4 in r.products and r.products[4]["match"] == "fuzzy"


def test_brand_fuzzy_spaced():
    idx = make_index()
    r = idx.entity.match("tu lanh sam sung")
    assert "Samsung" in r.brands


def test_no_false_product():
    idx = make_index()
    r = idx.entity.match("gia vang hom nay")
    assert not r.products and not r.brands
