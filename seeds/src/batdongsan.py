"""Demo 3: Bất động sản TP.HCM (dự án hư cấu): căn hộ, nhà phố, biệt thự, shophouse, đất nền, cho thuê."""
from __future__ import annotations

import random

from common import case, per_product_cases, set_status, strip_accents, write_demo

DEMO = {"slug": "batdongsan", "name": "Nhà Đẹp Sài Gòn Demo", "industry": "môi giới bất động sản TP.HCM"}

DISTRICTS = [("Quận 7", ["q7", "quận bảy", "phú mỹ hưng"]), ("Thủ Đức", ["tp thủ đức", "quận 9", "quận 2", "thủ thiêm"]),
             ("Bình Thạnh", ["bình thạnh", "q bình thạnh"]), ("Gò Vấp", ["gò vấp", "gv"]),
             ("Nhà Bè", ["nhà bè"]), ("Bình Chánh", ["bình chánh"])]
DEFS = [
    {"key": "giao_dich", "label": "Hình thức", "type": "enum", "filterable": True, "weight": 0.95,
     "enum_values": [{"value": "Bán", "aliases": ["mua", "bán", "sang nhượng", "cần mua"]},
                     {"value": "Cho thuê", "aliases": ["thuê", "cho thuê", "mướn", "cần thuê"]}]},
    {"key": "khu_vuc", "label": "Khu vực", "type": "enum", "filterable": True, "weight": 0.85,
     "enum_values": [{"value": v, "aliases": a} for v, a in DISTRICTS]},
    {"key": "dien_tich", "label": "Diện tích", "type": "number", "unit": "m2",
     "unit_aliases": ["m²", "mét vuông", "mét", "m vuông", "met vuong", "mv"], "filterable": True, "weight": 0.6},
    {"key": "so_phong_ngu", "label": "Số phòng ngủ", "type": "number", "unit": "phòng ngủ",
     "unit_aliases": ["pn", "phòng", "phòng ngủ", "phong ngu"], "filterable": True, "weight": 0.8},
    {"key": "so_wc", "label": "Số WC", "type": "number", "unit": "WC", "unit_aliases": ["toilet", "nhà vệ sinh", "vệ sinh", "wc"],
     "filterable": False, "weight": 0.3},
    {"key": "so_tang", "label": "Số tầng", "type": "number", "unit": "tầng", "unit_aliases": ["lầu", "tầng"],
     "filterable": True, "weight": 0.5},
    {"key": "huong", "label": "Hướng", "type": "enum", "filterable": True, "weight": 0.4,
     "enum_values": [{"value": v, "aliases": [f"hướng {v.lower()}"]} for v in
                     ["Đông", "Tây", "Nam", "Bắc", "Đông Nam", "Đông Bắc", "Tây Nam", "Tây Bắc"]]},
    {"key": "phap_ly", "label": "Pháp lý", "type": "enum", "filterable": True, "weight": 0.5,
     "enum_values": [{"value": "Sổ hồng", "aliases": ["có sổ", "sổ hồng riêng", "sổ riêng", "sổ đỏ"]},
                     {"value": "Hợp đồng mua bán", "aliases": ["hđmb", "chưa có sổ", "hợp đồng"]}]},
    {"key": "noi_that", "label": "Nội thất", "type": "enum", "filterable": True, "weight": 0.4,
     "enum_values": [{"value": "Đầy đủ", "aliases": ["full nội thất", "nội thất đầy đủ", "xách vali vào ở", "phun nội thất"]},
                     {"value": "Cơ bản", "aliases": ["nội thất cơ bản"]},
                     {"value": "Bàn giao thô", "aliases": ["nhà thô", "thô", "chưa nội thất"]}]},
    {"key": "tien_ich", "label": "Đặc điểm nổi bật", "type": "multi_enum", "filterable": False, "weight": 0.4,
     "enum_values": [{"value": v, "aliases": a} for v, a in [
         ("View sông", ["view sông", "nhìn ra sông", "ven sông"]), ("Hồ bơi", ["bể bơi", "hồ bơi"]),
         ("Mặt tiền", ["mặt đường", "mặt phố", "mặt tiền"]), ("Hẻm xe hơi", ["hẻm ô tô", "hẻm xe hơi", "ô tô vào nhà"]),
         ("Gần trường học", ["gần trường"]), ("Kinh doanh được", ["buôn bán", "kinh doanh"]),
         ("Căn góc", ["góc", "căn góc", "hai mặt tiền"])]]},
]

T = 1e9
TR = 1e6
# (sku, name, category, price, attrs, desc, spoken, spoken2, asr, alias_q, extra, ucs)
P = [
    ("CH-HS-1PN", "Căn hộ 1PN Hoa Sen Residence 50m2", "Căn hộ", 2.4 * T,
     {"giao_dich": "Bán", "khu_vuc": "Quận 7", "dien_tich": 50, "so_phong_ngu": 1, "so_wc": 1, "huong": "Đông Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["Hồ bơi"]},
     "Căn 1 phòng ngủ tầng trung, hồ bơi nội khu", "căn hộ 1 phòng ngủ hoa sen residence", "can ho 1pn hoa sen",
     "căn hộ một phòng ngủ hoa sen rê si đần", "hoa sen 1pn quận 7", ["hoa sen 1pn"], ["người độc thân, vợ chồng trẻ", "đầu tư cho thuê"]),
    ("CH-HS-2PN", "Căn hộ 2PN Hoa Sen Residence 72m2", "Căn hộ", 3.6 * T,
     {"giao_dich": "Bán", "khu_vuc": "Quận 7", "dien_tich": 72, "so_phong_ngu": 2, "so_wc": 2, "huong": "Đông",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["Hồ bơi", "Gần trường học"]},
     "Căn 2 phòng ngủ 2 WC, gần trường quốc tế", "căn hộ 2 phòng ngủ hoa sen residence", "can ho 2pn hoa sen",
     "căn hộ hai phòng ngủ hoa sen rê si đần", "hoa sen 2pn 72 mét", ["hoa sen 2pn"], ["gia đình trẻ có 1-2 con nhỏ"]),
    ("CH-HS-3PN", "Căn hộ 3PN Hoa Sen Residence 98m2", "Căn hộ", 5.2 * T,
     {"giao_dich": "Bán", "khu_vuc": "Quận 7", "dien_tich": 98, "so_phong_ngu": 3, "so_wc": 2, "huong": "Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["Hồ bơi", "Căn góc"]},
     "Căn góc 3 phòng ngủ thoáng 2 mặt", "căn hộ 3 phòng ngủ hoa sen residence", "can ho 3pn hoa sen",
     "căn hộ ba phòng ngủ hoa sen rê si đần", "hoa sen 3pn căn góc", ["hoa sen 3pn"], ["gia đình 3 thế hệ", "gia đình đông con"]),
    ("CH-SX-2PN", "Căn hộ 2PN Sông Xanh Tower 68m2 view sông", "Căn hộ", 4.1 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Thạnh", "dien_tich": 68, "so_phong_ngu": 2, "so_wc": 2, "huong": "Tây Bắc",
      "phap_ly": "Sổ hồng", "noi_that": "Đầy đủ", "tien_ich": ["View sông", "Hồ bơi"]},
     "Căn 2PN view sông Sài Gòn, full nội thất", "căn hộ 2 phòng ngủ sông xanh tower", "can ho 2pn song xanh",
     "căn hộ hai phòng ngủ sông xanh tao ơ", "sông xanh 2pn view sông", ["sông xanh 2pn"], ["thích view sông, gần trung tâm"]),
    ("CH-SX-3PN", "Căn hộ 3PN Sông Xanh Tower 105m2", "Căn hộ", 6.8 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Thạnh", "dien_tich": 105, "so_phong_ngu": 3, "so_wc": 2, "huong": "Đông Bắc",
      "phap_ly": "Sổ hồng", "noi_that": "Đầy đủ", "tien_ich": ["View sông", "Hồ bơi"]},
     "Căn 3PN rộng, view sông và Landmark", "căn hộ 3 phòng ngủ sông xanh tower", "can ho 3pn song xanh",
     "căn hộ ba phòng ngủ sông xanh tao ơ", "sông xanh 3pn 105 mét", ["sông xanh 3pn"], ["gia đình đông người cần gần trung tâm"]),
    ("CH-SX-PH", "Penthouse Sông Xanh Tower 180m2 4PN", "Căn hộ", 14.5 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Thạnh", "dien_tich": 180, "so_phong_ngu": 4, "so_wc": 4, "huong": "Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Đầy đủ", "tien_ich": ["View sông", "Hồ bơi"]},
     "Penthouse tầng thượng, sân vườn riêng, hồ bơi riêng", "penthouse sông xanh", "penthouse song xanh tower",
     "pen hao sông xanh", "căn áp mái sông xanh", ["penthouse", "căn áp mái"], ["người thu nhập cao, thích không gian riêng"]),
    ("CH-BM-1PN", "Căn hộ 1PN+1 Bình Minh Garden 55m2", "Căn hộ", 2.1 * T,
     {"giao_dich": "Bán", "khu_vuc": "Thủ Đức", "dien_tich": 55, "so_phong_ngu": 1, "so_wc": 1, "huong": "Tây",
      "phap_ly": "Hợp đồng mua bán", "noi_that": "Cơ bản", "tien_ich": ["Hồ bơi"]},
     "Căn 1PN+1 có phòng làm việc nhỏ, gần metro", "căn hộ 1 phòng ngủ cộng bình minh garden", "can ho 1pn+1 binh minh",
     "căn hộ một phòng ngủ cộng một bình minh ga đần", "bình minh 1pn+1 gần metro", ["bình minh 1pn+1"], ["người làm việc tại nhà", "gần metro đi làm"]),
    ("CH-BM-2PN", "Căn hộ 2PN Bình Minh Garden 70m2", "Căn hộ", 2.9 * T,
     {"giao_dich": "Bán", "khu_vuc": "Thủ Đức", "dien_tich": 70, "so_phong_ngu": 2, "so_wc": 2, "huong": "Đông",
      "phap_ly": "Hợp đồng mua bán", "noi_that": "Bàn giao thô", "tien_ich": ["Hồ bơi", "Gần trường học"]},
     "Căn 2PN bàn giao thô, giá tốt khu Thủ Đức", "căn hộ 2 phòng ngủ bình minh garden", "can ho 2pn binh minh",
     "căn hộ hai phòng ngủ bình minh ga đần", "bình minh 2pn bàn giao thô", ["bình minh 2pn"], ["gia đình trẻ muốn tự làm nội thất"]),
    ("CH-BM-ST", "Căn hộ Studio Bình Minh Garden 35m2", "Căn hộ", 1.45 * T,
     {"giao_dich": "Bán", "khu_vuc": "Thủ Đức", "dien_tich": 35, "so_phong_ngu": 1, "so_wc": 1, "huong": "Bắc",
      "phap_ly": "Hợp đồng mua bán", "noi_that": "Cơ bản"},
     "Studio nhỏ gọn giá dưới 1,5 tỷ", "căn studio bình minh garden", "can studio binh minh", "căn xờ tu đi ô bình minh",
     "studio bình minh 35 mét", ["studio bình minh"], ["sinh viên, người đi làm độc thân", "vốn ít muốn đầu tư"]),
    ("CH-GV-2PN", "Căn hộ 2PN Lan Anh Apartment Gò Vấp 65m2", "Căn hộ", 2.6 * T,
     {"giao_dich": "Bán", "khu_vuc": "Gò Vấp", "dien_tich": 65, "so_phong_ngu": 2, "so_wc": 2, "huong": "Đông Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["Gần trường học"]},
     "Căn hộ đã có sổ hồng, gần sân bay", "căn hộ lan anh gò vấp", "can ho lan anh go vap", "căn hộ lan anh a pát mần gò vấp",
     "chung cư gò vấp có sổ", ["lan anh apartment"], ["làm việc gần sân bay Tân Sơn Nhất"]),
    ("CH-NB-2PN", "Căn hộ 2PN Cảng Xanh Riverside Nhà Bè 75m2", "Căn hộ", 2.3 * T,
     {"giao_dich": "Bán", "khu_vuc": "Nhà Bè", "dien_tich": 75, "so_phong_ngu": 2, "so_wc": 2, "huong": "Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["View sông", "Hồ bơi"]},
     "Căn hộ ven sông giá mềm khu Nhà Bè", "căn hộ cảng xanh riverside", "can ho cang xanh riverside",
     "căn hộ cảng xanh ri vơ sai", "chung cư ven sông nhà bè", ["cảng xanh"], ["muốn view sông nhưng ngân sách vừa"]),
    ("CH-OT-Q7", "Officetel Hoa Sen 40m2", "Căn hộ", 1.8 * T,
     {"giao_dich": "Bán", "khu_vuc": "Quận 7", "dien_tich": 40, "so_phong_ngu": 1, "so_wc": 1, "huong": "Tây",
      "phap_ly": "Hợp đồng mua bán", "noi_that": "Cơ bản", "tien_ich": ["Kinh doanh được"]},
     "Officetel vừa ở vừa đăng ký kinh doanh", "officetel hoa sen", "officetel hoa sen quan 7", "óp phi teo hoa sen",
     "căn vừa ở vừa làm văn phòng quận 7", ["officetel"], ["mở văn phòng nhỏ, startup"]),
    ("NP-GV-4T", "Nhà phố Gò Vấp 4x15m 4 tầng hẻm xe hơi", "Nhà phố", 7.9 * T,
     {"giao_dich": "Bán", "khu_vuc": "Gò Vấp", "dien_tich": 60, "so_phong_ngu": 4, "so_wc": 4, "so_tang": 4, "huong": "Tây Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["Hẻm xe hơi"]},
     "Nhà 4 tầng hẻm 6m xe hơi vào nhà", "nhà phố gò vấp 4 tầng", "nha pho go vap 4 tang", "nhà phố gò vấp bốn tầng hẻm ô tô",
     "nhà hẻm xe hơi gò vấp", ["nhà gò vấp 4 tầng"], ["gia đình đông người cần đậu ô tô"]),
    ("NP-BT-3T", "Nhà mặt tiền Bình Thạnh 4x12m 3 tầng", "Nhà phố", 9.5 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Thạnh", "dien_tich": 48, "so_phong_ngu": 3, "so_wc": 3, "so_tang": 3, "huong": "Đông",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["Mặt tiền", "Kinh doanh được"]},
     "Nhà mặt tiền đường lớn, tiện buôn bán", "nhà mặt tiền bình thạnh", "nha mat tien binh thanh", "nhà mặt tiền bình thạnh ba tầng",
     "nhà mặt phố bình thạnh buôn bán", ["mặt tiền bình thạnh"], ["vừa ở vừa kinh doanh"]),
    ("NP-TD-5T", "Nhà phố Thủ Đức 5x20m 5 tầng", "Nhà phố", 12.8 * T,
     {"giao_dich": "Bán", "khu_vuc": "Thủ Đức", "dien_tich": 100, "so_phong_ngu": 6, "so_wc": 6, "so_tang": 5, "huong": "Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Đầy đủ", "tien_ich": ["Mặt tiền", "Kinh doanh được"]},
     "Nhà 5 tầng có thang máy, phù hợp căn hộ dịch vụ", "nhà phố thủ đức 5 tầng", "nha pho thu duc 5 tang",
     "nhà phố thủ đức năm tầng thang máy", "nhà làm căn hộ dịch vụ thủ đức", ["nhà 5 tầng thủ đức"], ["đầu tư căn hộ dịch vụ cho thuê"]),
    ("NP-BC-2T", "Nhà phố Bình Chánh 4x16m 2 tầng", "Nhà phố", 3.9 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Chánh", "dien_tich": 64, "so_phong_ngu": 3, "so_wc": 2, "so_tang": 2, "huong": "Bắc",
      "phap_ly": "Sổ hồng", "noi_that": "Cơ bản", "tien_ich": ["Hẻm xe hơi"]},
     "Nhà 1 trệt 1 lầu giá dưới 4 tỷ", "nhà phố bình chánh 2 tầng", "nha pho binh chanh", "nhà phố bình chánh một trệt một lầu",
     "nhà bình chánh dưới 4 tỷ", ["nhà bình chánh"], ["gia đình trẻ vốn vừa phải muốn ở nhà đất"]),
    ("NP-Q7-HEM", "Nhà hẻm Quận 7 3.5x10m 3 tầng", "Nhà phố", 4.6 * T,
     {"giao_dich": "Bán", "khu_vuc": "Quận 7", "dien_tich": 35, "so_phong_ngu": 2, "so_wc": 3, "so_tang": 3, "huong": "Đông Bắc",
      "phap_ly": "Sổ hồng", "noi_that": "Đầy đủ"},
     "Nhà hẻm 3m nhỏ xinh, gần Phú Mỹ Hưng", "nhà hẻm quận 7", "nha hem quan 7 3 tang", "nhà hẻm quận bảy ba tầng",
     "nhà nhỏ quận 7 gần phú mỹ hưng", ["nhà hẻm q7"], ["vợ chồng trẻ làm việc ở Quận 7"]),
    ("BT-PL-SL", "Biệt thự song lập Phú Lộc Villas 200m2", "Biệt thự", 28 * T,
     {"giao_dich": "Bán", "khu_vuc": "Thủ Đức", "dien_tich": 200, "so_phong_ngu": 4, "so_wc": 5, "so_tang": 3, "huong": "Đông Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Bàn giao thô", "tien_ich": ["Hồ bơi"]},
     "Biệt thự song lập khu compound an ninh", "biệt thự song lập phú lộc", "biet thu song lap phu loc",
     "biệt thự song lập phú lộc vi la", "phú lộc song lập", ["phú lộc song lập"], ["gia đình khá giả cần an ninh"]),
    ("BT-PL-DL", "Biệt thự đơn lập Phú Lộc Villas 350m2", "Biệt thự", 45 * T,
     {"giao_dich": "Bán", "khu_vuc": "Thủ Đức", "dien_tich": 350, "so_phong_ngu": 5, "so_wc": 6, "so_tang": 3, "huong": "Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Bàn giao thô", "tien_ich": ["Hồ bơi", "Căn góc"]},
     "Biệt thự đơn lập sân vườn, hồ bơi riêng", "biệt thự đơn lập phú lộc", "biet thu don lap phu loc",
     "biệt thự đơn lập phú lộc vi la", "phú lộc đơn lập có hồ bơi riêng", ["phú lộc đơn lập"], ["doanh nhân, gia đình nhiều thế hệ"]),
    ("BT-NB-VEN", "Biệt thự ven sông Nhà Bè 300m2", "Biệt thự", 22 * T,
     {"giao_dich": "Bán", "khu_vuc": "Nhà Bè", "dien_tich": 300, "so_phong_ngu": 4, "so_wc": 5, "so_tang": 2, "huong": "Tây",
      "phap_ly": "Sổ hồng", "noi_that": "Đầy đủ", "tien_ich": ["View sông"]},
     "Biệt thự nghỉ dưỡng ven sông, có bến thuyền", "biệt thự ven sông nhà bè", "biet thu ven song nha be",
     "biệt thự ven sông nhà bè có bến thuyền", "villa ven sông nhà bè", ["villa nhà bè"], ["nghỉ dưỡng cuối tuần, yên tĩnh"]),
    ("SH-NL-01", "Shophouse Ngọc Lan Quận 7 100m2 5 tầng", "Shophouse", 18 * T,
     {"giao_dich": "Bán", "khu_vuc": "Quận 7", "dien_tich": 100, "so_phong_ngu": 3, "so_wc": 5, "so_tang": 5, "huong": "Đông",
      "phap_ly": "Sổ hồng", "noi_that": "Bàn giao thô", "tien_ich": ["Mặt tiền", "Kinh doanh được"]},
     "Shophouse mặt tiền đại lộ, tầng trệt kinh doanh", "shophouse ngọc lan quận 7", "shophouse ngoc lan",
     "sóp hao ngọc lan quận bảy", "nhà phố thương mại ngọc lan", ["ngọc lan shophouse"], ["mở showroom, nhà hàng"]),
    ("SH-TP-02", "Shophouse Thịnh Phát Bình Chánh 90m2 4 tầng", "Shophouse", 9.8 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Chánh", "dien_tich": 90, "so_phong_ngu": 3, "so_wc": 4, "so_tang": 4, "huong": "Nam",
      "phap_ly": "Sổ hồng", "noi_that": "Bàn giao thô", "tien_ich": ["Mặt tiền", "Kinh doanh được"]},
     "Shophouse khu đô thị mới giá dưới 10 tỷ", "shophouse thịnh phát", "shophouse thinh phat binh chanh",
     "sóp hao thịnh phát bình chánh", "nhà phố thương mại bình chánh", ["thịnh phát shophouse"], ["kinh doanh khu dân cư mới"]),
    ("DN-TP-100", "Đất nền Thịnh Phát 100m2", "Đất nền", 2.8 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Chánh", "dien_tich": 100, "huong": "Đông", "phap_ly": "Sổ hồng"},
     "Đất nền sổ đỏ từng nền, đường 12m", "đất nền thịnh phát 100 mét", "dat nen thinh phat 100m2",
     "đất nền thịnh phát một trăm mét vuông", "lô đất 100 mét bình chánh", ["đất thịnh phát"], ["mua đất tự xây nhà", "đầu tư dài hạn"]),
    ("DN-TP-120G", "Đất nền góc Thịnh Phát 120m2", "Đất nền", 3.9 * T,
     {"giao_dich": "Bán", "khu_vuc": "Bình Chánh", "dien_tich": 120, "huong": "Đông Nam", "phap_ly": "Sổ hồng",
      "tien_ich": ["Căn góc", "Mặt tiền"]},
     "Lô góc 2 mặt tiền, thích hợp kinh doanh", "đất nền góc thịnh phát", "dat nen goc thinh phat",
     "đất nền góc thịnh phát một trăm hai mươi mét", "lô góc hai mặt tiền bình chánh", ["lô góc thịnh phát"], ["xây nhà kết hợp kinh doanh"]),
    ("DN-NB-80", "Đất nền Nhà Bè 80m2", "Đất nền", 2.2 * T,
     {"giao_dich": "Bán", "khu_vuc": "Nhà Bè", "dien_tich": 80, "huong": "Tây Bắc", "phap_ly": "Sổ hồng"},
     "Đất thổ cư 80m2 hẻm xe hơi", "đất nền nhà bè 80 mét", "dat nen nha be 80m2", "đất nền nhà bè tám mươi mét",
     "đất thổ cư nhà bè", ["đất nhà bè"], ["vốn ít muốn có đất"]),
    ("TH-HS-2PN", "Cho thuê căn hộ 2PN Hoa Sen Residence full nội thất", "Căn hộ", 15 * TR,
     {"giao_dich": "Cho thuê", "khu_vuc": "Quận 7", "dien_tich": 72, "so_phong_ngu": 2, "so_wc": 2, "noi_that": "Đầy đủ",
      "tien_ich": ["Hồ bơi"]},
     "Cho thuê dài hạn, xách vali vào ở", "thuê căn hộ 2 phòng ngủ hoa sen", "thue can ho 2pn hoa sen",
     "thuê căn hộ hai phòng ngủ hoa sen rê si đần", "thuê hoa sen 2pn full nội thất", ["thuê hoa sen 2pn"], ["chuyên gia nước ngoài, gia đình nhỏ thuê dài hạn"]),
    ("TH-SX-1PN", "Cho thuê căn hộ 1PN Sông Xanh Tower", "Căn hộ", 12 * TR,
     {"giao_dich": "Cho thuê", "khu_vuc": "Bình Thạnh", "dien_tich": 50, "so_phong_ngu": 1, "so_wc": 1, "noi_that": "Đầy đủ",
      "tien_ich": ["View sông"]},
     "Căn 1PN view sông cho thuê", "thuê căn hộ 1 phòng ngủ sông xanh", "thue can ho 1pn song xanh",
     "thuê căn hộ một phòng ngủ sông xanh tao ơ", "thuê sông xanh 1pn view sông", ["thuê sông xanh 1pn"], ["người đi làm trung tâm"]),
    ("TH-BM-ST", "Cho thuê studio Bình Minh Garden", "Căn hộ", 6.5 * TR,
     {"giao_dich": "Cho thuê", "khu_vuc": "Thủ Đức", "dien_tich": 35, "so_phong_ngu": 1, "so_wc": 1, "noi_that": "Cơ bản"},
     "Studio cho thuê giá rẻ gần làng đại học", "thuê studio bình minh", "thue studio binh minh garden",
     "thuê xờ tu đi ô bình minh", "thuê căn nhỏ gần làng đại học", ["thuê studio"], ["sinh viên, người mới đi làm"]),
    ("TH-NP-BT", "Cho thuê nhà nguyên căn Bình Thạnh 3 tầng", "Nhà phố", 25 * TR,
     {"giao_dich": "Cho thuê", "khu_vuc": "Bình Thạnh", "dien_tich": 60, "so_phong_ngu": 4, "so_wc": 3, "so_tang": 3,
      "noi_that": "Cơ bản", "tien_ich": ["Hẻm xe hơi"]},
     "Nhà nguyên căn hẻm xe hơi, làm văn phòng hoặc ở", "thuê nhà nguyên căn bình thạnh", "thue nha nguyen can binh thanh",
     "thuê nhà nguyên căn bình thạnh ba tầng", "thuê nguyên căn làm văn phòng", ["thuê nguyên căn"], ["làm văn phòng công ty nhỏ", "gia đình đông người thuê"]),
    ("TH-MB-Q7", "Cho thuê mặt bằng kinh doanh Quận 7 80m2", "Shophouse", 40 * TR,
     {"giao_dich": "Cho thuê", "khu_vuc": "Quận 7", "dien_tich": 80, "noi_that": "Bàn giao thô",
      "tien_ich": ["Mặt tiền", "Kinh doanh được"]},
     "Mặt bằng tầng trệt mặt tiền, phù hợp cafe, showroom", "thuê mặt bằng quận 7", "thue mat bang quan 7",
     "thuê mặt bằng quận bảy tám mươi mét", "mặt bằng mở quán cà phê quận 7", ["mặt bằng q7"], ["mở quán cà phê, cửa hàng"]),
]

QTPL = ["{name} giá bao nhiêu", "{short} còn không anh", "xem nhà {short} được không", "tôi cần {uc}"]


def build_products() -> list[dict]:
    out = []
    for (sku, name, cat, price, attrs, desc, spoken, spoken2, asr, alias_q, extra, ucs) in P:
        unit = "VND/tháng" if attrs.get("giao_dich") == "Cho thuê" else "VND"
        aliases = list(dict.fromkeys([spoken, strip_accents(spoken), *extra]))
        sq = [t.format(name=name, short=spoken, uc=ucs[0]) for t in QTPL]
        out.append({"sku": sku, "name": name, "category": cat, "brand": None, "price": price, "price_unit": unit,
                    "in_stock": True, "short_description": desc, "attributes": attrs, "aliases": aliases,
                    "use_cases": ucs, "sample_questions": sq, "enrichment_status": "reviewed",
                    "_spoken": spoken, "_spoken2": spoken2, "_spoken_asr": asr, "_alias_q": alias_q})
    return out


def build_cases(products: list[dict]) -> list[dict]:
    rnd = random.Random(13)
    cs = per_product_cases(products, rnd)
    A = lambda p, k: p["attributes"].get(k)  # noqa: E731
    sale = lambda p: A(p, "giao_dich") == "Bán"  # noqa: E731

    def where(fn):
        return [p["sku"] for p in products if fn(p)]

    for q, fn, cat in [
        ("căn hộ dưới 2 tỷ", lambda p: sale(p) and p["category"] == "Căn hộ" and p["price"] <= 2 * T, "price"),
        ("nhà phố tầm 8 tỷ", lambda p: sale(p) and p["category"] == "Nhà phố" and 6.4 * T <= p["price"] <= 9.6 * T, "price"),
        ("biệt thự rẻ nhất", lambda p: p["sku"] == "BT-NB-VEN", "price"),
        ("thuê căn hộ dưới 10 triệu", lambda p: A(p, "giao_dich") == "Cho thuê" and p["category"] == "Căn hộ" and p["price"] <= 10 * TR, "price"),
        ("đất nền từ 2 đến 3 tỷ", lambda p: p["category"] == "Đất nền" and 2 * T <= p["price"] <= 3 * T, "price"),
        ("can ho tam 3 ty ruoi", lambda p: sale(p) and p["category"] == "Căn hộ" and 2.8 * T <= p["price"] <= 4.2 * T, "price"),
        ("căn hộ 3 phòng ngủ", lambda p: sale(p) and A(p, "so_phong_ngu") == 3 and p["category"] == "Căn hộ", "numeric_attr"),
        ("nhà 5 tầng", lambda p: A(p, "so_tang") == 5, "numeric_attr"),
        ("căn hộ trên 100 mét vuông", lambda p: p["category"] == "Căn hộ" and sale(p) and A(p, "dien_tich") >= 100, "numeric_attr"),
        ("đất 80 mét vuông", lambda p: p["category"] == "Đất nền" and A(p, "dien_tich") == 80, "numeric_attr"),
        ("căn hộ quận 7 hai phòng ngủ", lambda p: sale(p) and p["category"] == "Căn hộ" and A(p, "khu_vuc") == "Quận 7" and A(p, "so_phong_ngu") == 2, "numeric_attr"),
        ("căn hộ có sổ hồng ở thủ đức", lambda p: p["category"] == "Căn hộ" and A(p, "khu_vuc") == "Thủ Đức" and A(p, "phap_ly") == "Sổ hồng", "numeric_attr"),
        ("nhà bàn giao thô ở thủ đức", lambda p: A(p, "khu_vuc") == "Thủ Đức" and A(p, "noi_that") == "Bàn giao thô", "numeric_attr"),
        ("căn hộ hướng nam bình thạnh", lambda p: p["category"] == "Căn hộ" and A(p, "khu_vuc") == "Bình Thạnh" and A(p, "huong") == "Nam", "numeric_attr"),
    ]:
        skus = where(fn)
        cs.append(case(q, skus, set_status(skus), cat))
    for q, skus, st in [
        ("vợ chồng mới cưới vốn khoảng 1 tỷ rưỡi muốn mua chỗ ở", ["CH-BM-ST"], "matched"),
        ("tôi muốn mở quán cà phê cần thuê mặt bằng", ["TH-MB-Q7"], "matched"),
        ("mua nhà vừa ở vừa buôn bán mặt tiền", ["NP-BT-3T", "NP-TD-5T", "SH-NL-01", "SH-TP-02"], "ambiguous"),
        ("cuối tuần muốn có chỗ nghỉ dưỡng yên tĩnh ven sông", ["BT-NB-VEN"], "matched"),
        ("công ty nhỏ cần thuê nguyên căn làm văn phòng", ["TH-NP-BT"], "matched"),
        ("sinh viên thuê phòng gần làng đại học", ["TH-BM-ST"], "matched"),
        ("đầu tư căn hộ dịch vụ cho thuê", ["NP-TD-5T"], "matched"),
        ("muốn mua đất tự xây nhà sổ đỏ", ["DN-TP-100", "DN-TP-120G", "DN-NB-80"], "ambiguous"),
        ("gia đình có ô tô cần nhà hẻm xe hơi gò vấp", ["NP-GV-4T"], "matched"),
        ("căn có phòng làm việc riêng gần metro", ["CH-BM-1PN"], "matched"),
        ("chuyên gia nước ngoài thuê căn hộ quận 7 đầy đủ nội thất", ["TH-HS-2PN"], "matched"),
        ("căn hộ có hồ bơi riêng sân vườn trên cao", ["CH-SX-PH"], "matched"),
        ("căn vừa ở vừa đăng ký kinh doanh được", ["CH-OT-Q7"], "matched"),
    ]:
        cs.append(case(q, skus, st, "use_case"))
    for q, skus in [
        ("căn hộ hoa sen residence", where(lambda p: "Hoa Sen Residence" in p["name"] and sale(p))),
        ("biệt thự phú lộc", ["BT-PL-SL", "BT-PL-DL"]),
        ("căn hộ sông xanh", where(lambda p: "Sông Xanh" in p["name"] and sale(p) and p["sku"] != "CH-SX-PH")),
        ("shophouse", ["SH-NL-01", "SH-TP-02"]),
        ("đất nền thịnh phát", ["DN-TP-100", "DN-TP-120G"]),
        ("căn hộ bình minh garden 2 phòng", ["CH-BM-2PN", "CH-BM-1PN"]),
    ]:
        cs.append(case(q, skus, "ambiguous", "ambiguous"))
    cs.append(case("so sánh căn 2 phòng ngủ hoa sen với sông xanh", ["CH-HS-2PN", "CH-SX-2PN"], "ambiguous", "compare"))
    for q, prev_text, prev, skus, st in [
        ("có căn 3 phòng ngủ không", "căn hộ 2 phòng ngủ hoa sen residence", ["CH-HS-2PN"], ["CH-HS-3PN"], "matched"),
        ("loại cho thuê thì sao", "căn hộ 2 phòng ngủ hoa sen residence", ["CH-HS-2PN"], ["TH-HS-2PN"], "matched"),
        ("căn đó hướng gì", "căn hộ 2 phòng ngủ sông xanh view sông", ["CH-SX-2PN"], ["CH-SX-2PN"], "matched"),
        ("có căn đơn lập không", "biệt thự song lập phú lộc", ["BT-PL-SL"], ["BT-PL-DL"], "matched"),
        ("lô góc giá bao nhiêu", "đất nền thịnh phát 100 mét", ["DN-TP-100"], ["DN-TP-120G"], "matched"),
        ("rộng hơn chút được không", "nhà hẻm quận 7", ["NP-Q7-HEM"], where(lambda p: p["category"] == "Nhà phố" and sale(p) and A(p, "dien_tich") > 35), None),
        ("nhà đó có sổ chưa", "căn hộ 2 phòng ngủ bình minh garden", ["CH-BM-2PN"], ["CH-BM-2PN"], "matched"),
    ]:
        cs.append(case(q, skus, st or set_status(skus), "multi_turn", {"previous_text": prev_text, "previous_skus": prev}))
    for q in ["lãi suất vay mua nhà ngân hàng nào thấp nhất", "thủ tục sang tên sổ đỏ mất bao lâu",
              "cho tôi số điện thoại giám đốc", "dự báo giá nhà đất năm sau tăng không", "hôm nay kẹt xe đường nào",
              "chào em anh hỏi thăm thôi"]:
        cs.append(case(q, [], "out_of_scope", "out_of_scope"))
    for q in ["căn hộ ở hà nội cầu giấy", "đất nông nghiệp long an", "biệt thự đà lạt", "căn hộ quận 1 dưới 2 tỷ",
              "condotel nha trang"]:
        cs.append(case(q, [], "no_match", "no_match"))
    return cs


if __name__ == "__main__":
    prods = build_products()
    cases = build_cases(prods)
    write_demo("batdongsan", DEMO, DEFS, [{k: v for k, v in p.items() if not k.startswith("_")} for p in prods], cases)
