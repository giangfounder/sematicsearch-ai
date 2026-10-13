import pytest

from app.text.normalize import normalize_query, strip_accents, tokens
from app.text.vn_numbers import spoken_to_digits


def test_normalize_removes_fillers_and_punct():
    s, na = normalize_query("Dạ, cho em hỏi: tủ lạnh Samsung ạ?")
    assert s == "tủ lạnh samsung"
    assert na == "tu lanh samsung"


def test_only_fillers_kept():
    assert normalize_query("dạ vâng ạ")[0] != ""


def test_keeps_decimal_and_range():
    assert normalize_query("giá 9,8 triệu, loại 2-3 người")[0] == "giá 9,8 triệu loại 2-3 người"


def test_strip_accents_d():
    assert strip_accents("Điều hòa đời mới") == "Dieu hoa doi moi"


def test_tokens_bigrams():
    assert tokens("tủ lạnh lg") == ["tủ", "lạnh", "lg", "tủ_lạnh", "lạnh_lg"]


@pytest.mark.parametrize("src,exp", [
    ("tủ lạnh mười lăm triệu", "tủ lạnh 15 triệu"),
    ("tivi bốn ba inch", "tivi 43 inch"),
    ("tầm hai ba triệu", "tầm 2-3 triệu"),
    ("chín triệu rưỡi", "9 triệu rưỡi"),
    ("một tỷ hai", "1 tỷ 2"),
    ("hai mươi lăm triệu", "25 triệu"),
    ("bảo hành hai năm", "bảo hành 2 năm"),
    ("một trăm linh năm", "105"),
    ("ba trăm lít", "300 lít"),
    ("năm nay có gì mới", "năm nay có gì mới"),
    ("ba mẹ tôi dùng", "ba mẹ tôi dùng"),
])
def test_spoken_numbers(src, exp):
    assert spoken_to_digits(src) == exp
