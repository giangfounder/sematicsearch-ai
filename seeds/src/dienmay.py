"""Demo 1: Điện máy (tủ lạnh, máy giặt, tivi, điều hoà, điện thoại). Giá hư cấu, chỉ để demo."""
from __future__ import annotations

import random

from common import case, per_product_cases, set_status, strip_accents, write_demo

DEMO = {"slug": "dienmay", "name": "Điện Máy Demo", "industry": "bán lẻ điện máy, điện thoại"}

DEFS = [
    {"key": "loai_tu", "label": "Kiểu tủ", "type": "enum", "filterable": True, "weight": 0.6,
     "enum_values": [{"value": "Ngăn đá trên", "aliases": ["ngăn đông trên", "ngăn đá ở trên"]},
                     {"value": "Ngăn đá dưới", "aliases": ["ngăn đông dưới", "ngăn đá ở dưới"]},
                     {"value": "Side by side", "aliases": ["side by side", "hai cánh dọc", "2 cánh dọc", "sai bai sai"]},
                     {"value": "Multi door", "aliases": ["multi door", "nhiều cửa", "4 cánh", "bốn cánh"]},
                     {"value": "Mini", "aliases": ["tủ mini", "tủ nhỏ", "1 cánh"]}]},
    {"key": "dung_tich", "label": "Dung tích", "type": "number", "unit": "lít", "unit_aliases": ["l", "lit"],
     "filterable": True, "weight": 0.6},
    {"key": "so_cua", "label": "Số cửa", "type": "number", "unit": "cửa", "unit_aliases": ["cánh", "canh", "cua"],
     "filterable": True, "weight": 0.7},
    {"key": "inverter", "label": "Inverter", "type": "bool", "label_aliases": ["tiết kiệm điện", "biến tần"],
     "filterable": False, "weight": 0.4},
    {"key": "khoi_luong_giat", "label": "Khối lượng giặt", "type": "number", "unit": "kg",
     "unit_aliases": ["ký", "kí", "ki lô", "cân", "kilogam"], "filterable": True, "weight": 0.7},
    {"key": "loai_may_giat", "label": "Kiểu máy giặt", "type": "enum", "filterable": True, "weight": 0.7,
     "enum_values": [{"value": "Cửa trước", "aliases": ["lồng ngang", "cửa ngang", "cửa trước"]},
                     {"value": "Cửa trên", "aliases": ["lồng đứng", "cửa đứng", "cửa trên"]}]},
    {"key": "say_kho", "label": "Sấy khô", "type": "bool", "label_aliases": ["có sấy", "giặt sấy", "sấy quần áo"],
     "filterable": True, "weight": 0.6},
    {"key": "man_hinh", "label": "Kích thước màn hình", "type": "number", "unit": "inch",
     "unit_aliases": ["in", "inh", "ins", "icnh", "inches"], "label_aliases": ["màn", "màn hình"],
     "filterable": True, "weight": 0.8},
    {"key": "do_phan_giai", "label": "Độ phân giải", "type": "enum", "filterable": True, "weight": 0.5,
     "enum_values": [{"value": "4K", "aliases": ["4 k", "bốn k", "uhd", "ultra hd"]},
                     {"value": "Full HD", "aliases": ["fhd", "full hd", "phun hd"]},
                     {"value": "HD", "aliases": ["hd thường"]}]},
    {"key": "cong_nghe_man_hinh", "label": "Công nghệ màn hình", "type": "enum", "filterable": True, "weight": 0.5,
     "enum_values": [{"value": "LED", "aliases": ["led thường"]}, {"value": "QLED", "aliases": ["qled", "kiu led"]},
                     {"value": "OLED", "aliases": ["oled", "ô lét"]}, {"value": "Mini LED", "aliases": ["mini led"]}]},
    {"key": "cong_suat_hp", "label": "Công suất", "type": "number", "unit": "HP",
     "unit_aliases": ["ngựa", "hp", "hờ pê", "mã lực", "sức ngựa"], "filterable": True, "weight": 0.8},
    {"key": "btu", "label": "Công suất làm lạnh", "type": "number", "unit": "BTU", "unit_aliases": ["btu"],
     "filterable": True, "weight": 0.5},
    {"key": "so_chieu", "label": "Số chiều", "type": "enum", "filterable": True, "weight": 0.7,
     "enum_values": [{"value": "1 chiều", "aliases": ["một chiều", "chỉ làm lạnh"]},
                     {"value": "2 chiều", "aliases": ["hai chiều", "nóng lạnh", "có sưởi", "sưởi ấm"]}]},
    {"key": "bo_nho", "label": "Bộ nhớ trong", "type": "number", "unit": "GB", "unit_aliases": ["gb", "gigabyte", "gi ga"],
     "label_aliases": ["dung lượng", "bộ nhớ"], "filterable": True, "weight": 0.6},
    {"key": "ram", "label": "RAM", "type": "number", "unit": "GB RAM", "filterable": False, "weight": 0.3},
]

# (sku, name, category, brand, price, in_stock, attrs, short_desc, spoken, spoken2, spoken_asr, alias_q, extra_aliases, use_cases)
P = [
    # ---------------- Tủ lạnh
    ("TL-SS-236", "Tủ lạnh Samsung Inverter 236 lít RT22M4032BY", "Tủ lạnh", "Samsung", 6290000, True,
     {"loai_tu": "Ngăn đá trên", "dung_tich": 236, "so_cua": 2, "inverter": True},
     "Tủ lạnh 2 cửa ngăn đá trên, làm lạnh vòm, tiết kiệm điện",
     "tủ lạnh samsung 236 lít", "tu lanh samsung 236l", "tủ lạnh samsung hai trăm ba sáu lít", "samsung 236 lít",
     ["RT22M4032BY", "tủ samsung 236"], ["gia đình 2-3 người", "căn hộ nhỏ", "tiết kiệm điện"]),
    ("TL-SS-305", "Tủ lạnh Samsung Inverter 305 lít RT29K5532BY", "Tủ lạnh", "Samsung", 8490000, True,
     {"loai_tu": "Ngăn đá trên", "dung_tich": 305, "so_cua": 2, "inverter": True},
     "Tủ lạnh 2 cửa có ngăn đông mềm, khử mùi than hoạt tính",
     "tủ lạnh samsung 305 lít", "tu lanh samsung 305 lit", "tủ lạnh samsung ba trăm linh năm lít", "samsung 305",
     ["RT29K5532BY"], ["gia đình 3-4 người", "trữ đồ ăn cả tuần"]),
    ("TL-SS-655", "Tủ lạnh Samsung Inverter 655 lít Side by side RS62R5001M9", "Tủ lạnh", "Samsung", 17990000, True,
     {"loai_tu": "Side by side", "dung_tich": 655, "so_cua": 2, "inverter": True},
     "Tủ lạnh 2 cánh dọc side by side dung tích lớn, ngăn đông rộng",
     "tủ lạnh samsung side by side 655 lít", "samsung side by side 655", "tủ lạnh sam sung sai bai sai sáu trăm năm lăm lít",
     "samsung 2 cánh dọc 655 lít", ["RS62R5001M9", "samsung side by side"], ["gia đình đông người 5-7 người", "nhà bếp rộng, sang trọng"]),
    ("TL-SS-488", "Tủ lạnh Samsung Inverter 488 lít Multi door RF48A4000B4", "Tủ lạnh", "Samsung", 19490000, True,
     {"loai_tu": "Multi door", "dung_tich": 488, "so_cua": 4, "inverter": True},
     "Tủ lạnh 4 cánh multi door, ngăn chuyển đổi nhiệt độ linh hoạt",
     "tủ lạnh samsung 4 cánh 488 lít", "tu lanh samsung multi door 488", "tủ lạnh samsung bốn cánh bốn trăm tám tám lít",
     "samsung multi door 488 lít", ["RF48A4000B4", "samsung 4 cánh"], ["gia đình 4-6 người", "bếp hiện đại, thích nhiều ngăn chia"]),
    ("TL-LG-335", "Tủ lạnh LG Inverter 335 lít GN-D332BL", "Tủ lạnh", "LG", 9190000, True,
     {"loai_tu": "Ngăn đá trên", "dung_tich": 335, "so_cua": 2, "inverter": True},
     "Tủ lạnh 2 cửa máy nén Smart Inverter, làm lạnh đa chiều",
     "tủ lạnh lg 335 lít", "tu lanh lg 335 lit", "tủ lạnh eo gi ba trăm ba lăm lít", "lg 335 lít",
     ["GN-D332BL", "tủ lg 335"], ["gia đình 3-4 người"]),
    ("TL-LG-635", "Tủ lạnh LG Inverter 635 lít Side by side GR-B257JDS", "Tủ lạnh", "LG", 16490000, True,
     {"loai_tu": "Side by side", "dung_tich": 635, "so_cua": 2, "inverter": True},
     "Tủ lạnh side by side lấy nước ngoài, làm đá tự động",
     "tủ lạnh lg side by side 635 lít", "lg side by side 635", "tủ lạnh lờ gờ sai bai sai sáu trăm ba lăm lít",
     "lg 2 cánh dọc có lấy nước ngoài", ["GR-B257JDS", "lg side by side"], ["gia đình đông người", "cần lấy nước lạnh ngoài tủ"]),
    ("TL-PA-322", "Tủ lạnh Panasonic Inverter 322 lít NR-BC360QKVN", "Tủ lạnh", "Panasonic", 11990000, True,
     {"loai_tu": "Ngăn đá dưới", "dung_tich": 322, "so_cua": 2, "inverter": True},
     "Tủ lạnh ngăn đá dưới, ngăn cấp đông mềm Prime Fresh, kháng khuẩn Ag",
     "tủ lạnh panasonic ngăn đá dưới 322 lít", "tu lanh panasonic ngan da duoi", "tủ lạnh pa na sô níc ba trăm hai hai lít ngăn đá dưới",
     "panasonic ngăn đông dưới 322", ["NR-BC360QKVN", "pana ngăn đá dưới"], ["gia đình 3-4 người", "người hay lấy đồ ngăn mát, đỡ phải cúi"]),
    ("TL-PA-255", "Tủ lạnh Panasonic Inverter 255 lít NR-TV261APSV", "Tủ lạnh", "Panasonic", 8790000, True,
     {"loai_tu": "Ngăn đá trên", "dung_tich": 255, "so_cua": 2, "inverter": True},
     "Tủ lạnh 2 cửa ngăn đá trên, công nghệ Blue Ag+ kháng khuẩn",
     "tủ lạnh panasonic 255 lít", "tu lanh panasonic 255 lit", "tủ lạnh pa na sô níc hai trăm năm lăm lít", "pana 255 lít",
     ["NR-TV261APSV"], ["gia đình 2-3 người"]),
    ("TL-TO-180", "Tủ lạnh Toshiba Inverter 180 lít GR-B22VU", "Tủ lạnh", "Toshiba", 5190000, True,
     {"loai_tu": "Ngăn đá trên", "dung_tich": 180, "so_cua": 2, "inverter": True},
     "Tủ lạnh 2 cửa nhỏ gọn, giá rẻ, tiết kiệm điện",
     "tủ lạnh toshiba 180 lít", "tu lanh toshiba 180", "tủ lạnh tô si ba một trăm tám mươi lít", "toshiba 180 lít",
     ["GR-B22VU"], ["vợ chồng trẻ 2 người", "phòng trọ, căn hộ nhỏ"]),
    ("TL-AQ-90", "Tủ lạnh mini Aqua 90 lít AQR-D99FA", "Tủ lạnh", "Aqua", 2890000, True,
     {"loai_tu": "Mini", "dung_tich": 90, "so_cua": 1, "inverter": False},
     "Tủ lạnh mini 1 cửa nhỏ gọn, đặt phòng ngủ, phòng trọ",
     "tủ lạnh mini aqua 90 lít", "tu lanh mini aqua", "tủ lạnh mi ni a qua chín mươi lít", "tủ mini aqua",
     ["AQR-D99FA", "tủ lạnh mini", "tủ lạnh 1 cửa"], ["sinh viên ở trọ", "phòng ngủ, văn phòng", "người ở một mình"]),
    ("TL-HI-569", "Tủ lạnh Hitachi Inverter 569 lít Multi door R-FW690PGV7", "Tủ lạnh", "Hitachi", 27990000, False,
     {"loai_tu": "Multi door", "dung_tich": 569, "so_cua": 4, "inverter": True},
     "Tủ lạnh 4 cánh cao cấp mặt kính, cảm biến thông minh",
     "tủ lạnh hitachi 569 lít", "tu lanh hitachi multi door", "tủ lạnh hi ta chi năm trăm sáu chín lít", "hitachi 4 cánh mặt kính",
     ["R-FW690PGV7"], ["gia đình lớn, thích hàng Nhật cao cấp"]),
    ("TL-CA-218", "Tủ lạnh Casper Inverter 218 lít RT-230PB", "Tủ lạnh", "Casper", 4690000, True,
     {"loai_tu": "Ngăn đá trên", "dung_tich": 218, "so_cua": 2, "inverter": True},
     "Tủ lạnh 2 cửa giá rẻ, inverter tiết kiệm điện",
     "tủ lạnh casper 218 lít", "tu lanh casper 218", "tủ lạnh cát pơ hai trăm mười tám lít", "casper 218 lít",
     ["RT-230PB"], ["gia đình 2-3 người", "ngân sách thấp"]),
    # ---------------- Máy giặt
    ("MG-SS-9", "Máy giặt Samsung Inverter 9 kg WW90T3040WW", "Máy giặt", "Samsung", 7990000, True,
     {"khoi_luong_giat": 9, "loai_may_giat": "Cửa trước", "inverter": True, "say_kho": False},
     "Máy giặt cửa trước giặt hơi nước diệt khuẩn",
     "máy giặt samsung 9 ký cửa trước", "may giat samsung 9kg", "máy giặt sam sung chín ký lồng ngang", "samsung 9kg cửa ngang",
     ["WW90T3040WW"], ["gia đình 4-5 người"]),
    ("MG-SS-10S", "Máy giặt sấy Samsung Inverter 10 kg WD10T634DBN", "Máy giặt", "Samsung", 14490000, True,
     {"khoi_luong_giat": 10, "loai_may_giat": "Cửa trước", "inverter": True, "say_kho": True},
     "Máy giặt sấy 2 trong 1, giặt 10 kg sấy 6 kg, AI Control",
     "máy giặt sấy samsung 10 ký", "may giat say samsung 10kg", "máy giặt sấy sam sung mười ký", "samsung giặt sấy 10kg",
     ["WD10T634DBN", "samsung giặt sấy"], ["chung cư không có chỗ phơi", "mùa nồm ẩm miền Bắc"]),
    ("MG-LG-9", "Máy giặt LG Inverter 9 kg FV1409S4W", "Máy giặt", "LG", 8290000, True,
     {"khoi_luong_giat": 9, "loai_may_giat": "Cửa trước", "inverter": True, "say_kho": False},
     "Máy giặt cửa trước AI DD, giặt hơi nước",
     "máy giặt lg 9 ký", "may giat lg 9kg", "máy giặt eo gi chín ký", "lg 9kg cửa trước",
     ["FV1409S4W"], ["gia đình 4-5 người"]),
    ("MG-LG-11S", "Máy giặt sấy LG Inverter 11 kg FV1411H3BA", "Máy giặt", "LG", 16990000, True,
     {"khoi_luong_giat": 11, "loai_may_giat": "Cửa trước", "inverter": True, "say_kho": True},
     "Máy giặt sấy 11 kg giặt 7 kg sấy, AI DD, hơi nước",
     "máy giặt sấy lg 11 ký", "may giat say lg 11kg", "máy giặt sấy lờ gờ mười một ký", "lg giặt sấy 11kg",
     ["FV1411H3BA", "lg giặt sấy"], ["gia đình đông người, cần sấy khô", "chung cư không có ban công phơi đồ"]),
    ("MG-TO-10", "Máy giặt Toshiba Inverter 10 kg AW-DUK1150HV", "Máy giặt", "Toshiba", 6990000, True,
     {"khoi_luong_giat": 10, "loai_may_giat": "Cửa trên", "inverter": True, "say_kho": False},
     "Máy giặt lồng đứng 10 kg, động cơ DD inverter",
     "máy giặt toshiba 10 ký lồng đứng", "may giat toshiba 10kg", "máy giặt tô si ba mười ký cửa trên", "toshiba lồng đứng 10kg",
     ["AW-DUK1150HV"], ["gia đình 5-6 người", "thích máy cửa trên dễ cho đồ"]),
    ("MG-AQ-8", "Máy giặt Aqua 8 kg AQW-S80CT", "Máy giặt", "Aqua", 3890000, True,
     {"khoi_luong_giat": 8, "loai_may_giat": "Cửa trên", "inverter": False, "say_kho": False},
     "Máy giặt lồng đứng giá rẻ, vận hành đơn giản",
     "máy giặt aqua 8 ký", "may giat aqua 8kg", "máy giặt a qua tám ký", "aqua 8kg lồng đứng",
     ["AQW-S80CT"], ["gia đình 3-4 người", "phòng trọ, ngân sách thấp"]),
    ("MG-PA-9", "Máy giặt Panasonic Inverter 9 kg NA-V90FC1LVT", "Máy giặt", "Panasonic", 9490000, True,
     {"khoi_luong_giat": 9, "loai_may_giat": "Cửa trước", "inverter": True, "say_kho": False},
     "Máy giặt cửa trước, giặt nước nóng diệt khuẩn",
     "máy giặt panasonic 9 ký", "may giat panasonic 9kg", "máy giặt pa na sô níc chín ký", "pana 9kg cửa trước",
     ["NA-V90FC1LVT"], ["gia đình có trẻ nhỏ cần giặt diệt khuẩn"]),
    ("MG-EL-10", "Máy giặt Electrolux Inverter 10 kg EWF1024P5WB", "Máy giặt", "Electrolux", 9990000, True,
     {"khoi_luong_giat": 10, "loai_may_giat": "Cửa trước", "inverter": True, "say_kho": False},
     "Máy giặt cửa trước UltraMix hoà tan bột giặt, hơi nước",
     "máy giặt electrolux 10 ký", "may giat electrolux 10kg", "máy giặt e léc trô lúc mười ký", "electrolux 10kg",
     ["EWF1024P5WB"], ["gia đình 5-6 người"]),
    ("MG-SH-12", "Máy giặt Sharp 12 kg ES-Y120HV", "Máy giặt", "Sharp", 5290000, True,
     {"khoi_luong_giat": 12, "loai_may_giat": "Cửa trên", "inverter": False, "say_kho": False},
     "Máy giặt lồng đứng 12 kg, giặt chăn mền",
     "máy giặt sharp 12 ký", "may giat sharp 12kg", "máy giặt sáp mười hai ký", "sharp 12kg",
     ["ES-Y120HV"], ["gia đình đông người", "giặt chăn mền, rèm cửa"]),
    ("MG-CA-75", "Máy giặt Casper 7.5 kg WT-75NG1", "Máy giặt", "Casper", 3290000, True,
     {"khoi_luong_giat": 7.5, "loai_may_giat": "Cửa trên", "inverter": False, "say_kho": False},
     "Máy giặt lồng đứng nhỏ gọn giá rẻ nhất",
     "máy giặt casper 7 ký rưỡi", "may giat casper 7.5kg", "máy giặt cát pơ bảy ký rưỡi", "casper 7.5kg",
     ["WT-75NG1"], ["sinh viên, người ở một mình", "phòng trọ"]),
    # ---------------- Tivi
    ("TV-SS-55Q", "Smart Tivi QLED Samsung 4K 55 inch QA55Q60D", "Tivi", "Samsung", 13990000, True,
     {"man_hinh": 55, "do_phan_giai": "4K", "cong_nghe_man_hinh": "QLED"},
     "Tivi QLED chấm lượng tử, màu sắc rực rỡ, Tizen OS",
     "tivi samsung qled 55 inch", "tivi samsung qled 55", "ti vi sam sung kiu led năm lăm in", "samsung qled 55",
     ["QA55Q60D", "qled 55"], ["phòng khách vừa", "xem bóng đá, phim màu sắc đẹp"]),
    ("TV-SS-43", "Smart Tivi Samsung 4K 43 inch UA43DU7000", "Tivi", "Samsung", 7490000, True,
     {"man_hinh": 43, "do_phan_giai": "4K", "cong_nghe_man_hinh": "LED"},
     "Tivi 4K 43 inch phổ thông, Tizen OS",
     "tivi samsung 43 inch", "tivi samsung 43", "ti vi sam sung bốn ba in", "samsung 43 inch",
     ["UA43DU7000"], ["phòng ngủ", "phòng khách nhỏ"]),
    ("TV-SS-65", "Smart Tivi Samsung 4K 65 inch UA65DU8000", "Tivi", "Samsung", 15990000, True,
     {"man_hinh": 65, "do_phan_giai": "4K", "cong_nghe_man_hinh": "LED"},
     "Tivi 4K 65 inch màn lớn, Crystal UHD",
     "tivi samsung 65 inch", "tivi samsung 65", "ti vi sam sung sáu lăm in", "samsung 65 inch",
     ["UA65DU8000"], ["phòng khách rộng"]),
    ("TV-LG-55O", "Smart Tivi OLED LG 4K 55 inch OLED55B4PSA", "Tivi", "LG", 29990000, True,
     {"man_hinh": 55, "do_phan_giai": "4K", "cong_nghe_man_hinh": "OLED"},
     "Tivi OLED tự phát sáng, màu đen sâu, 120Hz chơi game",
     "tivi lg oled 55 inch", "tivi lg oled 55", "ti vi lờ gờ ô lét năm lăm in", "lg oled 55",
     ["OLED55B4PSA", "oled lg"], ["xem phim chất lượng cao", "chơi game console"]),
    ("TV-LG-50", "Smart Tivi LG 4K 50 inch 50UR7550PSC", "Tivi", "LG", 8990000, True,
     {"man_hinh": 50, "do_phan_giai": "4K", "cong_nghe_man_hinh": "LED"},
     "Tivi 4K 50 inch webOS, điều khiển giọng nói",
     "tivi lg 50 inch", "tivi lg 50", "ti vi eo gi năm mươi in", "lg 50 inch",
     ["50UR7550PSC"], ["phòng khách vừa"]),
    ("TV-SO-55", "Google Tivi Sony 4K 55 inch KD-55X80L", "Tivi", "Sony", 16490000, True,
     {"man_hinh": 55, "do_phan_giai": "4K", "cong_nghe_man_hinh": "LED"},
     "Google TV Sony 4K, chip X1, âm thanh tốt",
     "tivi sony 55 inch", "tivi sony 55", "ti vi sô ni năm lăm in", "sony 55 inch",
     ["KD-55X80L"], ["phòng khách vừa", "thích hệ điều hành Google TV"]),
    ("TV-SO-65M", "Google Tivi Mini LED Sony 4K 65 inch K-65XR70", "Tivi", "Sony", 34990000, False,
     {"man_hinh": 65, "do_phan_giai": "4K", "cong_nghe_man_hinh": "Mini LED"},
     "Tivi Mini LED cao cấp, độ sáng cao, Bravia 7",
     "tivi sony mini led 65 inch", "tivi sony mini led", "ti vi xô ni mi ni led sáu lăm in", "sony bravia 7 65 inch",
     ["K-65XR70", "bravia 7"], ["phòng khách rộng, thích hàng cao cấp"]),
    ("TV-TC-43F", "Google Tivi TCL Full HD 43 inch 43S5400", "Tivi", "TCL", 4990000, True,
     {"man_hinh": 43, "do_phan_giai": "Full HD", "cong_nghe_man_hinh": "LED"},
     "Google TV giá rẻ Full HD",
     "tivi tcl 43 inch", "tivi tcl 43", "ti vi tê xê eo bốn ba in", "tcl 43 inch full hd",
     ["43S5400"], ["phòng ngủ", "ngân sách thấp"]),
    ("TV-XI-32", "Tivi Xiaomi A Pro HD 32 inch", "Tivi", "Xiaomi", 3990000, True,
     {"man_hinh": 32, "do_phan_giai": "HD", "cong_nghe_man_hinh": "LED"},
     "Tivi nhỏ 32 inch Google TV giá rẻ",
     "tivi xiaomi 32 inch", "tivi xiaomi 32", "ti vi xao mi ba hai in", "xiaomi 32 inch",
     ["xiaomi a pro 32"], ["phòng ngủ nhỏ, phòng trọ", "bếp, phòng ông bà"]),
    ("TV-CA-75", "Smart Tivi Casper 4K 75 inch 75UGS610", "Tivi", "Casper", 14990000, True,
     {"man_hinh": 75, "do_phan_giai": "4K", "cong_nghe_man_hinh": "LED"},
     "Tivi màn hình rất lớn 75 inch giá mềm",
     "tivi casper 75 inch", "tivi casper 75", "ti vi cát pơ bảy lăm in", "casper 75 inch",
     ["75UGS610"], ["phòng khách rất rộng, hội trường nhỏ", "muốn màn to giá rẻ"]),
    # ---------------- Điều hoà
    ("DH-DA-1", "Điều hòa Daikin Inverter 1 HP FTKB25XVMV", "Điều hòa", "Daikin", 10490000, True,
     {"cong_suat_hp": 1, "btu": 9000, "so_chieu": "1 chiều", "inverter": True},
     "Điều hoà 1 chiều 9000 BTU, bền bỉ, tiết kiệm điện",
     "điều hòa daikin 1 ngựa", "dieu hoa daikin 1hp", "điều hoà đai kin một ngựa", "máy lạnh daikin 9000 btu",
     ["FTKB25XVMV", "máy lạnh daikin 1hp"], ["phòng dưới 15 m2", "phòng ngủ nhỏ"]),
    ("DH-DA-15-2C", "Điều hòa 2 chiều Daikin Inverter 1.5 HP FTHF35XVMV", "Điều hòa", "Daikin", 15990000, True,
     {"cong_suat_hp": 1.5, "btu": 12000, "so_chieu": "2 chiều", "inverter": True},
     "Điều hoà 2 chiều làm lạnh và sưởi ấm, 12000 BTU",
     "điều hòa daikin 2 chiều 1.5 ngựa", "dieu hoa daikin 2 chieu", "điều hoà đai kin hai chiều một ngựa rưỡi",
     "daikin nóng lạnh 12000 btu", ["FTHF35XVMV", "daikin 2 chiều"], ["phòng 15-20 m2", "miền Bắc cần sưởi mùa đông"]),
    ("DH-PA-1", "Điều hòa Panasonic Inverter 1 HP CU/CS-XU9ZKH-8", "Điều hòa", "Panasonic", 12990000, True,
     {"cong_suat_hp": 1, "btu": 9000, "so_chieu": "1 chiều", "inverter": True},
     "Điều hoà cao cấp lọc không khí nanoe X",
     "điều hòa panasonic 1 ngựa", "dieu hoa panasonic 1hp", "điều hoà pa na sô níc một ngựa", "máy lạnh pana 9000",
     ["CU/CS-XU9ZKH-8", "pana nanoe"], ["phòng ngủ có trẻ nhỏ, cần lọc không khí"]),
    ("DH-PA-2", "Điều hòa Panasonic Inverter 2 HP CU/CS-U18ZKH-8", "Điều hòa", "Panasonic", 19490000, True,
     {"cong_suat_hp": 2, "btu": 18000, "so_chieu": "1 chiều", "inverter": True},
     "Điều hoà 18000 BTU cho phòng lớn",
     "điều hòa panasonic 2 ngựa", "dieu hoa panasonic 2hp", "điều hoà pa na sô níc hai ngựa", "pana 18000 btu",
     ["CU/CS-U18ZKH-8"], ["phòng khách 20-30 m2"]),
    ("DH-LG-15", "Điều hòa LG Inverter 1.5 HP V13WIN1", "Điều hòa", "LG", 9990000, True,
     {"cong_suat_hp": 1.5, "btu": 12000, "so_chieu": "1 chiều", "inverter": True},
     "Điều hoà 12000 BTU dual inverter làm lạnh nhanh",
     "điều hòa lg 1.5 ngựa", "dieu hoa lg 1.5hp", "điều hoà lờ gờ một ngựa rưỡi", "lg 12000 btu",
     ["V13WIN1"], ["phòng 15-20 m2"]),
    ("DH-CA-1", "Điều hòa Casper 1 HP KC-09FC32", "Điều hòa", "Casper", 5490000, True,
     {"cong_suat_hp": 1, "btu": 9000, "so_chieu": "1 chiều", "inverter": False},
     "Điều hoà 1 chiều giá rẻ, không inverter",
     "điều hòa casper 1 ngựa", "dieu hoa casper 1hp", "điều hoà cát pơ một ngựa", "máy lạnh casper rẻ",
     ["KC-09FC32"], ["phòng trọ, ngân sách thấp", "phòng dưới 15 m2"]),
    ("DH-TO-1", "Điều hòa Toshiba Inverter 1 HP RAS-H10C4KCVG-V", "Điều hòa", "Toshiba", 9490000, True,
     {"cong_suat_hp": 1, "btu": 9000, "so_chieu": "1 chiều", "inverter": True},
     "Điều hoà inverter 1 HP vận hành êm",
     "điều hòa toshiba 1 ngựa", "dieu hoa toshiba 1hp", "điều hoà tô si ba một ngựa", "máy lạnh toshiba 9000",
     ["RAS-H10C4KCVG-V"], ["phòng ngủ dưới 15 m2"]),
    ("DH-SS-2", "Điều hòa Samsung Inverter 2 HP AR18DYHZAWKNSV", "Điều hòa", "Samsung", 16490000, True,
     {"cong_suat_hp": 2, "btu": 18000, "so_chieu": "1 chiều", "inverter": True},
     "Điều hoà WindFree 2 HP không gió buốt",
     "điều hòa samsung 2 ngựa", "dieu hoa samsung 2hp", "điều hoà sam sung hai ngựa", "samsung windfree 18000",
     ["AR18DYHZAWKNSV", "samsung windfree"], ["phòng khách 20-30 m2", "người không thích gió thổi trực tiếp"]),
    # ---------------- Điện thoại
    ("DT-IP15PM", "iPhone 15 Pro Max 256GB", "Điện thoại", "Apple", 28990000, True,
     {"bo_nho": 256, "ram": 8}, "iPhone khung titan, camera zoom 5x, chip A17 Pro",
     "iphone 15 pro max 256gb", "iphone 15 pro max", "ai phôn mười lăm pờ rô mác", "15 pro max",
     ["ip 15 pro max", "15 promax", "táo 15 pro max"], ["chụp ảnh quay phim chuyên nghiệp", "doanh nhân"]),
    ("DT-IP15", "iPhone 15 128GB", "Điện thoại", "Apple", 19490000, True,
     {"bo_nho": 128, "ram": 6}, "iPhone 15 bản thường, Dynamic Island, cổng USB-C",
     "iphone 15 thường 128gb", "iphone 15 128", "ai phôn mười lăm bản thường", "ip 15 thường",
     ["ip 15", "iphone 15 thường"], ["người mới chuyển sang iPhone", "dùng cơ bản, bền"]),
    ("DT-IP16PM", "iPhone 16 Pro Max 256GB", "Điện thoại", "Apple", 33990000, True,
     {"bo_nho": 256, "ram": 8}, "iPhone mới nhất, nút Camera Control, màn 6.9 inch",
     "iphone 16 pro max", "iphone 16 promax", "ai phôn mười sáu pro mác", "16 pro max",
     ["ip 16 pro max", "táo 16 pro max"], ["người thích đời mới nhất", "quay video 4K 120fps"]),
    ("DT-SS-A55", "Samsung Galaxy A55 5G 8GB/128GB", "Điện thoại", "Samsung", 9490000, True,
     {"bo_nho": 128, "ram": 8}, "Điện thoại tầm trung khung kim loại, chống nước IP67",
     "samsung galaxy a55", "samsung a55", "sam sung ga la xi a năm lăm", "galaxy a55",
     ["a55", "ss a55"], ["học sinh sinh viên", "tầm trung pin trâu"]),
    ("DT-SS-S24U", "Samsung Galaxy S24 Ultra 12GB/256GB", "Điện thoại", "Samsung", 26990000, True,
     {"bo_nho": 256, "ram": 12}, "Flagship có bút S Pen, zoom 100x, Galaxy AI",
     "samsung s24 ultra", "s24 ultra", "sam sung ét hai bốn un tra", "galaxy s24 ultra",
     ["s24u", "ss s24 ultra"], ["doanh nhân cần bút ghi chú", "chụp ảnh zoom xa"]),
    ("DT-XI-RN13", "Xiaomi Redmi Note 13 8GB/128GB", "Điện thoại", "Xiaomi", 4890000, True,
     {"bo_nho": 128, "ram": 8}, "Điện thoại giá rẻ màn AMOLED 120Hz, pin 5000mAh",
     "xiaomi redmi note 13", "redmi note 13", "xao mi rét mi nốt mười ba", "redmi note 13 8gb",
     ["note 13", "xiaomi note 13"], ["học sinh, người lớn tuổi", "ngân sách dưới 5 triệu"]),
    ("DT-OP-R12F", "OPPO Reno12 F 5G 8GB/256GB", "Điện thoại", "OPPO", 8990000, True,
     {"bo_nho": 256, "ram": 8}, "Điện thoại chụp chân dung đẹp, sạc nhanh 45W",
     "oppo reno12 f", "oppo reno 12f", "óp pô rê nô mười hai ép", "reno 12 f",
     ["reno12f", "oppo reno 12"], ["bạn nữ thích chụp ảnh selfie", "sinh viên"]),
]

QTPL = ["{name} giá bao nhiêu", "{brand} {cat} {spec} còn hàng không", "tư vấn giúp mình {short}",
        "{cat} nào phù hợp {uc}", "mình muốn mua {short}, có trả góp không"]


def spec_text(attrs: dict) -> str:
    keys = ["dung_tich", "khoi_luong_giat", "man_hinh", "cong_suat_hp", "bo_nho"]
    units = {"dung_tich": "lít", "khoi_luong_giat": "kg", "man_hinh": "inch", "cong_suat_hp": "HP", "bo_nho": "GB"}
    for k in keys:
        if k in attrs:
            v = attrs[k]
            return f"{int(v) if float(v).is_integer() else v} {units[k]}"
    return ""


def build_products() -> list[dict]:
    out = []
    for (sku, name, cat, brand, price, stock, attrs, desc, spoken, spoken2, asr, alias_q, extra, ucs) in P:
        short = spoken
        aliases = list(dict.fromkeys([short, strip_accents(short), *extra]))
        sq = [t.format(name=name, brand=brand, cat=cat.lower(), spec=spec_text(attrs), short=short, uc=ucs[0])
              for t in QTPL]
        out.append({"sku": sku, "name": name, "category": cat, "brand": brand, "price": price, "price_unit": "VND",
                    "in_stock": stock, "short_description": desc, "attributes": attrs, "aliases": aliases,
                    "use_cases": ucs, "sample_questions": sq, "enrichment_status": "reviewed",
                    "_spoken": spoken, "_spoken2": spoken2, "_spoken_asr": asr, "_alias_q": alias_q})
    return out


def build_cases(products: list[dict]) -> list[dict]:
    rnd = random.Random(5)
    by_cat = {}
    for p in products:
        by_cat.setdefault(p["category"], []).append(p)
    cs = per_product_cases(products, rnd)

    def where(cat, fn):
        return [p["sku"] for p in by_cat[cat] if fn(p)]

    # theo giá (tính từ dữ liệu)
    for q, cat, fn in [
        ("tủ lạnh dưới 5 triệu", "Tủ lạnh", lambda p: p["price"] <= 5e6),
        ("cho em xem tủ lạnh tầm 9 triệu", "Tủ lạnh", lambda p: 7.2e6 <= p["price"] <= 10.8e6),
        ("máy giặt rẻ nhất bên mình", "Máy giặt", lambda p: p["sku"] == "MG-CA-75"),
        ("máy giặt từ 8 đến 10 triệu", "Máy giặt", lambda p: 8e6 <= p["price"] <= 10e6),
        ("tivi khoảng mười lăm củ", "Tivi", lambda p: 12e6 <= p["price"] <= 18e6),
        ("ti vi dưới bốn triệu", "Tivi", lambda p: p["price"] <= 4e6),
        ("điều hòa dưới 6 triệu", "Điều hòa", lambda p: p["price"] <= 6e6),
        ("điện thoại tầm năm triệu", "Điện thoại", lambda p: 4e6 <= p["price"] <= 6e6),
        ("điện thoại đắt nhất shop", "Điện thoại", lambda p: p["sku"] == "DT-IP16PM"),
        ("may giat duoi 4 trieu", "Máy giặt", lambda p: p["price"] <= 4e6),
        ("tủ lạnh trên 15 triệu còn hàng", "Tủ lạnh", lambda p: p["price"] >= 15e6 and p["in_stock"]),
    ]:
        skus = where(cat, fn)
        cs.append(case(q, skus, set_status(skus), "price"))
    # theo thuộc tính số / enum
    for q, cat, fn in [
        ("tivi 65 inch", "Tivi", lambda p: p["attributes"].get("man_hinh") == 65),
        ("tivi bảy lăm in", "Tivi", lambda p: p["attributes"].get("man_hinh") == 75),
        ("máy giặt 12 ký", "Máy giặt", lambda p: p["attributes"].get("khoi_luong_giat") == 12),
        ("máy giặt có sấy khô", "Máy giặt", lambda p: p["attributes"].get("say_kho")),
        ("điều hòa hai ngựa", "Điều hòa", lambda p: p["attributes"].get("cong_suat_hp") == 2),
        ("điều hòa hai chiều", "Điều hòa", lambda p: p["attributes"].get("so_chieu") == "2 chiều"),
        ("tủ lạnh side by side", "Tủ lạnh", lambda p: p["attributes"].get("loai_tu") == "Side by side"),
        ("tủ lạnh trên 500 lít", "Tủ lạnh", lambda p: p["attributes"].get("dung_tich", 0) >= 500),
        ("tủ lạnh ngăn đá dưới", "Tủ lạnh", lambda p: p["attributes"].get("loai_tu") == "Ngăn đá dưới"),
        ("tivi oled", "Tivi", lambda p: p["attributes"].get("cong_nghe_man_hinh") == "OLED"),
        ("máy giặt lồng đứng 10 ký", "Máy giặt", lambda p: p["attributes"].get("loai_may_giat") == "Cửa trên" and p["attributes"]["khoi_luong_giat"] == 10),
        ("tivi full hd 43 inch", "Tivi", lambda p: p["attributes"].get("do_phan_giai") == "Full HD"),
        ("dien thoai 256gb duoi 10 trieu", "Điện thoại", lambda p: p["attributes"].get("bo_nho") == 256 and p["price"] <= 10e6),
    ]:
        skus = where(cat, fn)
        cs.append(case(q, skus, set_status(skus), "numeric_attr"))
    # theo công dụng (viết tay)
    for q, skus, st in [
        ("em ở trọ một mình muốn mua cái tủ lạnh nhỏ thôi", ["TL-AQ-90"], "matched"),
        ("nhà chung cư không có chỗ phơi đồ thì nên mua máy nào", ["MG-SS-10S", "MG-LG-11S"], "ambiguous"),
        ("phòng ngủ khoảng 12 mét vuông lắp điều hòa loại nào rẻ mà tiết kiệm điện", ["DH-TO-1", "DH-DA-1", "DH-PA-1"], "ambiguous"),
        ("nhà ngoài bắc mùa đông lạnh cần máy lạnh có sưởi", ["DH-DA-15-2C"], "matched"),
        ("tivi để chơi ps5 màu đen sâu", ["TV-LG-55O"], "matched"),
        ("máy giặt giặt được chăn mền to", ["MG-SH-12"], "matched"),
        ("tủ lạnh lấy nước lạnh bên ngoài không cần mở cửa", ["TL-LG-635"], "matched"),
        ("điện thoại có bút để ghi chú", ["DT-SS-S24U"], "matched"),
        ("điện thoại cho bố mẹ dùng giá rẻ pin trâu", ["DT-XI-RN13"], "matched"),
        ("máy lạnh không thổi gió buốt vào người", ["DH-SS-2"], "matched"),
        ("điều hòa có lọc bụi mịn cho em bé", ["DH-PA-1"], "matched"),
        ("tủ lạnh cho nhà 6 7 người ăn", ["TL-SS-655", "TL-LG-635", "TL-SS-488", "TL-HI-569"], "ambiguous"),
        ("máy giặt cho người ở một mình giá rẻ", ["MG-CA-75"], "matched"),
        ("điện thoại selfie đẹp cho con gái", ["DT-OP-R12F"], "matched"),
    ]:
        cs.append(case(q, skus, st, "use_case"))
    # mơ hồ cần hỏi lại
    for q, skus in [
        ("tủ lạnh samsung", where("Tủ lạnh", lambda p: p["brand"] == "Samsung")),
        ("máy giặt lg", where("Máy giặt", lambda p: p["brand"] == "LG")),
        ("tivi sony", where("Tivi", lambda p: p["brand"] == "Sony")),
        ("điều hòa daikin", where("Điều hòa", lambda p: p["brand"] == "Daikin")),
        ("iphone pro max", ["DT-IP15PM", "DT-IP16PM"]),
        ("tivi 55 inch", where("Tivi", lambda p: p["attributes"].get("man_hinh") == 55)),
        ("điều hòa 1 ngựa inverter", where("Điều hòa", lambda p: p["attributes"].get("cong_suat_hp") == 1 and p["attributes"]["inverter"])),
    ]:
        cs.append(case(q, skus, "ambiguous", "ambiguous"))
    cs.append(case("so sánh giúp em iphone 15 pro max với s24 ultra", ["DT-IP15PM", "DT-SS-S24U"], "ambiguous", "compare"))
    cs.append(case("tủ lạnh lg 335 với panasonic 322 cái nào tốt hơn", ["TL-LG-335", "TL-PA-322"], "ambiguous", "compare"))
    # nhiều lượt
    for q, prev_text, prev, skus, st in [
        ("loại 2 chiều thì sao", "điều hòa daikin 1 ngựa", ["DH-DA-1"], ["DH-DA-15-2C"], "matched"),
        ("có bản sấy không em", "máy giặt lg 9 ký", ["MG-LG-9"], ["MG-LG-11S"], "matched"),
        ("cái đó giá bao nhiêu", "tivi lg oled 55 inch", ["TV-LG-55O"], ["TV-LG-55O"], "matched"),
        ("còn loại 65 inch không", "tivi samsung 43 inch", ["TV-SS-43"], ["TV-SS-65"], "matched"),
        ("bản pro max đời mới hơn có không", "iphone 15 pro max", ["DT-IP15PM"], ["DT-IP16PM"], "matched"),
        ("loại rẻ hơn chút", "tủ lạnh samsung 305 lít", ["TL-SS-305"], where("Tủ lạnh", lambda p: p["brand"] == "Samsung" and p["price"] < 8490000), None),
        ("thế còn 4 cánh", "tủ lạnh samsung side by side", ["TL-SS-655"], ["TL-SS-488"], "matched"),
        ("bảo hành bao lâu", "máy giặt toshiba 10 ký lồng đứng", ["MG-TO-10"], ["MG-TO-10"], "matched"),
    ]:
        cs.append(case(q, skus, st or set_status(skus), "multi_turn",
                       {"previous_text": prev_text, "previous_skus": prev}))
    # ngoài phạm vi / không có hàng
    for q in ["hôm nay trời có mưa không em", "cho chị đặt bàn ăn tối nay", "giá vàng hôm nay bao nhiêu",
              "em ơi kể chuyện cười đi", "số tổng đài khiếu nại điện lực là gì", "cảm ơn em nhé chào em",
              "tuyển dụng nhân viên bán hàng không"]:
        cs.append(case(q, [], "out_of_scope", "out_of_scope"))
    for q in ["máy rửa bát bosch", "nồi chiên không dầu philips", "laptop dell xps 13", "xe máy honda vision",
              "tủ lạnh electrolux 400 lít", "máy hút bụi dyson"]:
        cs.append(case(q, [], "no_match", "no_match"))
    return cs


if __name__ == "__main__":
    prods = build_products()
    cases = build_cases(prods)
    write_demo("dienmay", DEMO, DEFS, [{k: v for k, v in p.items() if not k.startswith("_")} for p in prods], cases)
