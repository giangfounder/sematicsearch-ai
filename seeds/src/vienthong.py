"""Demo 2: Viễn thông (nhà mạng hư cấu VNet): gói data, combo, internet cáp quang, truyền hình, chuyển vùng."""
from __future__ import annotations

import random

from common import case, per_product_cases, set_status, strip_accents, write_demo

DEMO = {"slug": "vienthong", "name": "VNet Viễn Thông Demo", "industry": "viễn thông di động, internet, truyền hình",
        "settings": {"fillers": ["tổng đài ơi", "cho mình đăng ký", "em muốn đăng ký"]}}

DEFS = [
    {"key": "data_ngay", "label": "Data mỗi ngày", "type": "number", "unit": "GB/ngày",
     "unit_aliases": ["gb một ngày", "gb mỗi ngày", "gb 1 ngày", "gb ngày", "gb/ngày", "gi ga một ngày", "gigabyte một ngày"],
     "filterable": True, "weight": 0.8},
    {"key": "data_thang", "label": "Data cả tháng", "type": "number", "unit": "GB/tháng",
     "unit_aliases": ["gb một tháng", "gb cả tháng", "gb tháng", "gb/tháng"], "filterable": True, "weight": 0.6},
    {"key": "chu_ky", "label": "Chu kỳ", "type": "enum", "filterable": True, "weight": 0.6,
     "enum_values": [{"value": "1 ngày", "aliases": ["theo ngày", "gói ngày", "một ngày"]},
                     {"value": "7 ngày", "aliases": ["theo tuần", "gói tuần", "một tuần", "bảy ngày"]},
                     {"value": "30 ngày", "aliases": ["theo tháng", "gói tháng", "một tháng"]},
                     {"value": "6 tháng", "aliases": ["nửa năm", "sáu tháng", "gói dài kỳ 6 tháng"]},
                     {"value": "12 tháng", "aliases": ["một năm", "cả năm", "mười hai tháng", "gói năm"]},
                     {"value": "15 ngày", "aliases": ["mười lăm ngày", "nửa tháng"]}]},
    {"key": "mien_phi_noi_mang", "label": "Miễn phí gọi nội mạng", "type": "bool",
     "label_aliases": ["free nội mạng", "gọi nội mạng miễn phí", "nội mạng thả ga", "gọi nội mạng"], "filterable": True, "weight": 0.6},
    {"key": "phut_ngoai_mang", "label": "Phút gọi ngoại mạng", "type": "number", "unit": "phút ngoại mạng",
     "unit_aliases": ["phút gọi ngoại mạng", "phút liên mạng"], "filterable": True, "weight": 0.5},
    {"key": "toc_do", "label": "Tốc độ", "type": "number", "unit": "Mbps",
     "unit_aliases": ["mb", "mega", "mbps", "mê ga", "mờ bê"], "filterable": True, "weight": 0.8},
    {"key": "wifi_mesh", "label": "Wifi Mesh", "type": "bool",
     "label_aliases": ["mesh", "kích sóng", "phủ sóng nhiều tầng", "wifi mét"], "filterable": True, "weight": 0.5},
    {"key": "so_kenh", "label": "Số kênh truyền hình", "type": "number", "unit": "kênh", "filterable": True, "weight": 0.5},
    {"key": "doi_tuong", "label": "Đối tượng", "type": "enum", "filterable": True, "weight": 0.6,
     "enum_values": [{"value": "Cá nhân", "aliases": []}, {"value": "Gia đình", "aliases": ["cả nhà", "nhóm gia đình"]},
                     {"value": "Sinh viên", "aliases": ["học sinh", "sinh viên", "sv"]},
                     {"value": "Doanh nghiệp", "aliases": ["công ty", "văn phòng", "doanh nghiệp"]}]},
    {"key": "ung_dung_mien_phi", "label": "Ứng dụng miễn phí data", "type": "multi_enum", "filterable": True, "weight": 0.6,
     "enum_values": [{"value": "TikTok", "aliases": ["tik tok", "tóp tóp"]}, {"value": "YouTube", "aliases": ["du túp", "yu túp"]},
                     {"value": "Facebook", "aliases": ["phây búc", "phở bò", "fb"]}, {"value": "Zalo", "aliases": ["da lô"]},
                     {"value": "Netflix", "aliases": ["nét phlích", "nét flix"]}]},
    {"key": "quoc_gia", "label": "Quốc gia chuyển vùng", "type": "multi_enum", "filterable": True, "weight": 0.8,
     "enum_values": [{"value": "Hàn Quốc", "aliases": ["hàn", "korea"]}, {"value": "Nhật Bản", "aliases": ["nhật", "japan"]},
                     {"value": "Thái Lan", "aliases": ["thái"]}, {"value": "Singapore", "aliases": ["sing", "xinh ga po"]},
                     {"value": "Trung Quốc", "aliases": ["trung", "tàu"]}, {"value": "Mỹ", "aliases": ["hoa kỳ", "usa"]},
                     {"value": "Châu Âu", "aliases": ["châu âu", "pháp", "đức", "ý"]},
                     {"value": "Úc", "aliases": ["australia", "ốt trây li a"]}]},
]

ASIA = ["Hàn Quốc", "Nhật Bản", "Thái Lan", "Singapore", "Trung Quốc"]
# (sku, name, category, price, price_unit, attrs, desc, spoken, spoken2, asr, alias_q, extra_aliases, use_cases)
P = [
    ("D10", "Gói ngày D10", "Gói data", 10000, "VND/ngày", {"data_ngay": 2, "chu_ky": "1 ngày", "doi_tuong": "Cá nhân"},
     "2GB tốc độ cao dùng trong 24 giờ", "gói d10", "goi d10 ngay", "gói đê mười", "gói ngày 10 nghìn 2 gb",
     ["đê 10", "d mười"], ["dùng gấp trong ngày", "đi công tác ngắn"]),
    ("D15", "Gói ngày D15", "Gói data", 15000, "VND/ngày", {"data_ngay": 3, "chu_ky": "1 ngày", "doi_tuong": "Cá nhân"},
     "3GB tốc độ cao dùng trong 24 giờ", "gói d15", "goi d15", "gói đê mười lăm", "gói ngày 3 gb 15 nghìn",
     ["đê 15"], ["xem phim một buổi", "cần nhiều data trong ngày"]),
    ("W50", "Gói tuần W50", "Gói data", 50000, "VND/7 ngày", {"data_ngay": 2, "chu_ky": "7 ngày", "doi_tuong": "Cá nhân"},
     "2GB/ngày dùng 7 ngày", "gói w50", "goi w50 tuan", "gói vê kép năm mươi", "gói tuần 50 nghìn",
     ["vê kép 50", "đúp bờ liu 50", "gói tuần"], ["đi du lịch trong nước 1 tuần"]),
    ("MXH70", "Gói MXH70 mạng xã hội", "Gói data", 70000, "VND/tháng",
     {"data_ngay": 1, "chu_ky": "30 ngày", "ung_dung_mien_phi": ["TikTok", "Facebook", "YouTube"], "doi_tuong": "Cá nhân"},
     "1GB/ngày + miễn phí data TikTok, Facebook, YouTube", "gói mxh70", "goi mxh70 mang xa hoi", "gói mờ xờ hờ bảy mươi",
     "gói lướt tiktok facebook miễn phí", ["mxh 70", "gói mạng xã hội"], ["người hay lướt TikTok, Facebook", "giới trẻ"]),
    ("SV50", "Gói sinh viên SV50", "Gói data", 50000, "VND/tháng", {"data_ngay": 1, "chu_ky": "30 ngày", "doi_tuong": "Sinh viên"},
     "Gói ưu đãi sinh viên 1GB/ngày", "gói sv50", "goi sv50 sinh vien", "gói ét vê năm mươi", "gói data cho sinh viên 50 nghìn",
     ["sv 50", "gói sinh viên"], ["học sinh sinh viên", "ngân sách thấp"]),
    ("D90", "Gói tháng D90", "Gói data", 90000, "VND/tháng", {"data_ngay": 1.5, "chu_ky": "30 ngày", "doi_tuong": "Cá nhân"},
     "1.5GB/ngày dùng 30 ngày", "gói d90", "goi d90 thang", "gói đê chín mươi", "gói tháng 1 gb rưỡi mỗi ngày",
     ["đê 90", "d chín mươi"], ["dùng data cơ bản hằng ngày"]),
    ("D120", "Gói tháng D120", "Gói data", 120000, "VND/tháng", {"data_ngay": 2, "chu_ky": "30 ngày", "doi_tuong": "Cá nhân"},
     "2GB/ngày dùng 30 ngày", "gói d120", "goi d120", "gói đê một trăm hai mươi", "gói tháng 2 gb mỗi ngày",
     ["đê 120", "d một hai mươi"], ["xem video, làm việc online"]),
    ("D150", "Gói tháng D150", "Gói data", 150000, "VND/tháng", {"data_ngay": 4, "chu_ky": "30 ngày", "doi_tuong": "Cá nhân"},
     "4GB/ngày dùng 30 ngày", "gói d150", "goi d150 4gb", "gói đê một trăm năm mươi", "gói 4 gb một ngày giá 150",
     ["đê 150"], ["xem phim, livestream nhiều"]),
    ("MAX200", "Gói MAX200", "Gói data", 200000, "VND/tháng",
     {"data_ngay": 6, "chu_ky": "30 ngày", "ung_dung_mien_phi": ["Netflix"], "doi_tuong": "Cá nhân"},
     "6GB/ngày + tài khoản Netflix", "gói max200", "goi max200 netflix", "gói mắc hai trăm", "gói data kèm netflix",
     ["max 200", "mắc 200"], ["dùng data rất nhiều", "thích xem Netflix trên điện thoại"]),
    ("D90-6T", "Gói D90 chu kỳ 6 tháng", "Gói data", 450000, "VND/6 tháng",
     {"data_ngay": 1.5, "chu_ky": "6 tháng", "doi_tuong": "Cá nhân"},
     "1.5GB/ngày, đóng 6 tháng tặng 1 tháng", "gói d90 6 tháng", "goi d90 6 thang", "gói đê chín mươi sáu tháng",
     "gói 90 đóng nửa năm", ["6d90", "d90 dài kỳ"], ["muốn đóng một lần dùng lâu, đỡ gia hạn"]),
    ("D120-12T", "Gói D120 chu kỳ 12 tháng", "Gói data", 1200000, "VND/12 tháng",
     {"data_ngay": 2, "chu_ky": "12 tháng", "doi_tuong": "Cá nhân"},
     "2GB/ngày, đóng 12 tháng tặng 2 tháng", "gói d120 12 tháng", "goi d120 12 thang", "gói đê một trăm hai mươi mười hai tháng",
     "gói 120 đóng cả năm", ["12d120", "d120 năm"], ["đóng một lần cả năm tiết kiệm nhất"]),
    ("TH30", "Gói tháng TH30 30GB", "Gói data", 100000, "VND/tháng", {"data_thang": 30, "chu_ky": "30 ngày", "doi_tuong": "Cá nhân"},
     "30GB dùng thoải mái trong tháng, không giới hạn theo ngày", "gói th30", "goi th30 30gb", "gói tê hát ba mươi",
     "gói 30 gb cả tháng không chia ngày", ["tê hát 30", "th 30"], ["người dùng không đều, có ngày nhiều ngày ít"]),
    ("TT5", "Gói tiết kiệm TT5", "Gói data", 30000, "VND/tháng", {"data_thang": 5, "chu_ky": "30 ngày", "doi_tuong": "Cá nhân"},
     "5GB/tháng giá rẻ cho người dùng ít", "gói tt5", "goi tt5 tiet kiem", "gói tê tê năm", "gói 30 nghìn 5 gb",
     ["tê tê 5"], ["người lớn tuổi chỉ dùng Zalo", "dùng data rất ít"]),
    # ---------------- Combo thoại + data
    ("C90", "Gói combo C90", "Gói combo", 90000, "VND/tháng",
     {"data_ngay": 1, "chu_ky": "30 ngày", "mien_phi_noi_mang": True, "phut_ngoai_mang": 30, "doi_tuong": "Cá nhân"},
     "1GB/ngày, miễn phí gọi nội mạng dưới 10 phút, 30 phút ngoại mạng", "gói combo c90", "goi c90 combo",
     "gói xê chín mươi", "gói 90 nghìn có gọi nội mạng", ["xê 90", "c chín mươi"], ["vừa gọi vừa dùng data ít"]),
    ("V120", "Gói combo V120", "Gói combo", 120000, "VND/tháng",
     {"data_ngay": 1.5, "chu_ky": "30 ngày", "mien_phi_noi_mang": True, "phut_ngoai_mang": 50, "doi_tuong": "Cá nhân"},
     "1.5GB/ngày, miễn phí nội mạng, 50 phút ngoại mạng", "gói combo v120", "goi v120", "gói vê một trăm hai mươi",
     "gói combo 120 nghìn có 50 phút ngoại mạng", ["vê 120", "v một hai mươi"], ["người gọi điện nhiều"]),
    ("V160", "Gói combo V160", "Gói combo", 160000, "VND/tháng",
     {"data_ngay": 4, "chu_ky": "30 ngày", "mien_phi_noi_mang": True, "phut_ngoai_mang": 100, "doi_tuong": "Cá nhân"},
     "4GB/ngày, miễn phí nội mạng, 100 phút ngoại mạng", "gói combo v160", "goi v160", "gói vê một trăm sáu mươi",
     "combo 4 gb ngày 100 phút ngoại mạng", ["vê 160"], ["vừa gọi nhiều vừa dùng data nhiều", "nhân viên kinh doanh"]),
    ("V200", "Gói combo V200", "Gói combo", 200000, "VND/tháng",
     {"data_ngay": 6, "chu_ky": "30 ngày", "mien_phi_noi_mang": True, "phut_ngoai_mang": 200, "doi_tuong": "Cá nhân"},
     "6GB/ngày, miễn phí nội mạng, 200 phút ngoại mạng", "gói combo v200", "goi v200", "gói vê hai trăm",
     "combo 200 phút ngoại mạng", ["vê 200"], ["gọi điện cực nhiều", "chủ shop online"]),
    ("GD300", "Gói gia đình GD300", "Gói combo", 300000, "VND/tháng",
     {"data_ngay": 8, "chu_ky": "30 ngày", "mien_phi_noi_mang": True, "phut_ngoai_mang": 150, "doi_tuong": "Gia đình"},
     "Chia sẻ 8GB/ngày cho tối đa 4 thuê bao, gọi nội nhóm miễn phí", "gói gia đình gd300", "goi gia dinh gd300",
     "gói giê đê ba trăm", "gói cho cả nhà 4 sim", ["gia đình 300", "gd 300"], ["gia đình 3-4 người dùng chung", "bố mẹ và con cái"]),
    ("DN250", "Gói doanh nghiệp DN250", "Gói combo", 250000, "VND/tháng",
     {"data_ngay": 5, "chu_ky": "30 ngày", "mien_phi_noi_mang": True, "phut_ngoai_mang": 300, "doi_tuong": "Doanh nghiệp"},
     "Gói cho nhân viên doanh nghiệp, 300 phút ngoại mạng, xuất hoá đơn VAT", "gói doanh nghiệp dn250", "goi dn250",
     "gói đê en hai trăm năm mươi", "gói sim công ty xuất hóa đơn", ["dn 250", "gói công ty"], ["doanh nghiệp cấp sim cho nhân viên"]),
    # ---------------- Internet cáp quang
    ("NET150", "Internet cáp quang Super 150Mbps", "Internet cáp quang", 180000, "VND/tháng",
     {"toc_do": 150, "wifi_mesh": False, "doi_tuong": "Cá nhân"}, "Cáp quang 150Mbps kèm modem wifi 6",
     "cáp quang 150 mega", "cap quang 150mbps", "cáp quang một trăm năm mươi mê ga", "internet 150 mb",
     ["super 150", "net 150"], ["nhà nhỏ 1-2 người", "phòng trọ, căn hộ studio"]),
    ("NET300", "Internet cáp quang Super 300Mbps", "Internet cáp quang", 230000, "VND/tháng",
     {"toc_do": 300, "wifi_mesh": False, "doi_tuong": "Gia đình"}, "Cáp quang 300Mbps cho gia đình",
     "cáp quang 300 mega", "cap quang 300", "cáp quang ba trăm mê ga", "internet 300 mb gia đình",
     ["super 300", "net 300"], ["gia đình 3-4 người", "học online, làm việc tại nhà"]),
    ("NET500M", "Internet cáp quang Mesh 500Mbps", "Internet cáp quang", 290000, "VND/tháng",
     {"toc_do": 500, "wifi_mesh": True, "doi_tuong": "Gia đình"}, "Cáp quang 500Mbps kèm 1 thiết bị Wifi Mesh",
     "cáp quang mesh 500 mega", "cap quang mesh 500", "cáp quang mét năm trăm mê ga", "internet 500 có mesh",
     ["mesh 500", "net 500"], ["nhà 2-3 tầng cần phủ sóng", "gia đình đông người"]),
    ("NET1G", "Internet cáp quang Giga 1Gbps", "Internet cáp quang", 450000, "VND/tháng",
     {"toc_do": 1000, "wifi_mesh": True, "doi_tuong": "Gia đình"}, "Cáp quang 1Gbps kèm 2 thiết bị Wifi Mesh",
     "cáp quang 1 giga", "cap quang 1gbps", "cáp quang một gi ga", "internet nhanh nhất 1000 mega",
     ["giga 1g", "net 1g", "1000 mbps"], ["nhà phố nhiều tầng", "streamer, game thủ"]),
    ("NETSV", "Internet sinh viên 100Mbps", "Internet cáp quang", 150000, "VND/tháng",
     {"toc_do": 100, "wifi_mesh": False, "doi_tuong": "Sinh viên"}, "Cáp quang ưu đãi sinh viên, không cần đóng trước",
     "internet sinh viên", "internet sinh vien 100mb", "in tơ nét sinh viên", "mạng cho phòng trọ sinh viên",
     ["net sinh viên", "cáp quang sinh viên"], ["sinh viên ở trọ", "ngân sách thấp"]),
    ("NETDN", "Internet doanh nghiệp 800Mbps IP tĩnh", "Internet cáp quang", 690000, "VND/tháng",
     {"toc_do": 800, "wifi_mesh": True, "doi_tuong": "Doanh nghiệp"}, "Cáp quang doanh nghiệp, IP tĩnh, cam kết băng thông quốc tế",
     "internet doanh nghiệp ip tĩnh", "internet doanh nghiep", "in tơ nét doanh nghiệp ai pi tĩnh", "cáp quang cho công ty có ip tĩnh",
     ["net doanh nghiệp", "ip tĩnh"], ["văn phòng công ty", "chạy camera, server"]),
    # ---------------- Truyền hình
    ("TVBASIC", "Truyền hình cơ bản 150 kênh", "Truyền hình", 80000, "VND/tháng",
     {"so_kenh": 150}, "150 kênh trong nước và quốc tế, xem lại 7 ngày", "truyền hình cơ bản", "truyen hinh co ban 150 kenh",
     "truyền hình cơ bản một trăm năm mươi kênh", "gói tivi 150 kênh", ["tv cơ bản"], ["xem thời sự, phim truyền hình"]),
    ("TVPREMIUM", "Truyền hình Premium 200 kênh + K+", "Truyền hình", 160000, "VND/tháng",
     {"so_kenh": 200}, "200 kênh kèm gói K+ xem bóng đá Ngoại hạng Anh", "truyền hình premium k+", "truyen hinh premium",
     "truyền hình pờ ri mi um ca cộng", "gói xem bóng đá ngoại hạng anh", ["premium", "gói k+"], ["fan bóng đá", "xem thể thao trực tiếp"]),
    ("COMBO-NT1", "Combo Internet 300Mbps + Truyền hình 150 kênh", "Truyền hình", 260000, "VND/tháng",
     {"toc_do": 300, "so_kenh": 150, "wifi_mesh": False, "doi_tuong": "Gia đình"}, "Combo cáp quang 300Mbps và truyền hình cơ bản",
     "combo internet 300 với truyền hình", "combo net tv 300", "com bô in tơ nét ba trăm truyền hình", "lắp cả mạng lẫn tivi gói 300",
     ["combo nt1", "combo mạng truyền hình"], ["gia đình muốn lắp cả mạng và truyền hình"]),
    ("COMBO-NT2", "Combo Internet Mesh 500Mbps + Truyền hình 200 kênh K+", "Truyền hình", 360000, "VND/tháng",
     {"toc_do": 500, "so_kenh": 200, "wifi_mesh": True, "doi_tuong": "Gia đình"}, "Combo cáp quang 500Mbps Mesh và truyền hình Premium K+",
     "combo internet 500 mesh với truyền hình k+", "combo net tv 500 k+", "com bô năm trăm mét ca cộng",
     "combo mạng mesh kèm xem bóng đá", ["combo nt2"], ["nhà nhiều tầng, mê bóng đá"]),
    # ---------------- Chuyển vùng quốc tế
    ("RM-ASIA", "Chuyển vùng Châu Á 7 ngày 5GB", "Chuyển vùng quốc tế", 199000, "VND/7 ngày",
     {"data_thang": 5, "chu_ky": "7 ngày", "quoc_gia": ASIA}, "5GB dùng tại 5 nước Châu Á trong 7 ngày",
     "gói chuyển vùng châu á", "goi roaming chau a", "gói rô minh châu á", "data đi du lịch thái lan singapore",
     ["roaming châu á", "rm asia"], ["du lịch Thái Lan, Singapore ngắn ngày"]),
    ("RM-JPKR", "Chuyển vùng Nhật Hàn 7 ngày 6GB", "Chuyển vùng quốc tế", 249000, "VND/7 ngày",
     {"data_thang": 6, "chu_ky": "7 ngày", "quoc_gia": ["Nhật Bản", "Hàn Quốc"]}, "6GB tốc độ cao tại Nhật Bản và Hàn Quốc",
     "gói chuyển vùng nhật hàn", "goi roaming nhat han", "gói rô minh nhật hàn", "data đi hàn quốc nhật bản",
     ["roaming nhật hàn"], ["du lịch, công tác Nhật Bản Hàn Quốc"]),
    ("RM-GLOBAL", "Chuyển vùng toàn cầu 15 ngày 10GB", "Chuyển vùng quốc tế", 499000, "VND/15 ngày",
     {"data_thang": 10, "chu_ky": "15 ngày", "quoc_gia": ASIA + ["Mỹ", "Châu Âu", "Úc"]}, "10GB dùng tại hơn 60 quốc gia trong 15 ngày",
     "gói chuyển vùng toàn cầu", "goi roaming toan cau", "gói rô minh toàn cầu", "data đi mỹ châu âu",
     ["roaming toàn cầu", "rm global"], ["đi Mỹ, Châu Âu, Úc", "công tác nhiều nước"]),
]

QTPL = ["đăng ký {short} như thế nào", "{name} được bao nhiêu data", "{short} giá bao nhiêu tiền",
        "gói nào {uc}", "hủy {short} được không"]


def build_products() -> list[dict]:
    out = []
    for (sku, name, cat, price, unit, attrs, desc, spoken, spoken2, asr, alias_q, extra, ucs) in P:
        aliases = list(dict.fromkeys([spoken, strip_accents(spoken), sku.lower(), *extra]))
        sq = [t.format(name=name, short=spoken, uc=ucs[0]) for t in QTPL]
        out.append({"sku": sku, "name": name, "category": cat, "brand": "VNet", "price": price, "price_unit": unit,
                    "in_stock": True, "short_description": desc, "attributes": attrs, "aliases": aliases,
                    "use_cases": ucs, "sample_questions": sq, "enrichment_status": "reviewed",
                    "_spoken": spoken, "_spoken2": spoken2, "_spoken_asr": asr, "_alias_q": alias_q})
    return out


def build_cases(products: list[dict]) -> list[dict]:
    rnd = random.Random(9)
    cs = per_product_cases(products, rnd)
    A = lambda p, k: p["attributes"].get(k)  # noqa: E731

    def where(fn):
        return [p["sku"] for p in products if fn(p)]

    for q, fn, cat in [
        ("gói data dưới 50 nghìn một tháng", lambda p: p["price"] <= 50000 and A(p, "chu_ky") == "30 ngày", "price"),
        ("gói tháng tầm 100 nghìn", lambda p: p["category"] == "Gói data" and A(p, "chu_ky") == "30 ngày" and 80000 <= p["price"] <= 120000, "price"),
        ("internet rẻ nhất", lambda p: p["sku"] == "NETSV", "price"),
        ("cáp quang dưới 200 nghìn", lambda p: p["category"] == "Internet cáp quang" and p["price"] <= 200000, "price"),
        ("gói combo trên 150 nghìn", lambda p: p["category"] == "Gói combo" and p["price"] >= 150000, "price"),
        ("goi data gia re nhat", lambda p: p["sku"] == "D10", "price"),
        ("gói 4 gb một ngày", lambda p: A(p, "data_ngay") == 4, "numeric_attr"),
        ("gói 6 gb mỗi ngày", lambda p: A(p, "data_ngay") == 6, "numeric_attr"),
        ("mạng 500 mega", lambda p: A(p, "toc_do") == 500, "numeric_attr"),
        ("cáp quang 1000 mbps", lambda p: A(p, "toc_do") == 1000, "numeric_attr"),
        ("gói có 200 phút ngoại mạng", lambda p: A(p, "phut_ngoai_mang") == 200, "numeric_attr"),
        ("gói 30 gb cả tháng", lambda p: A(p, "data_thang") == 30, "numeric_attr"),
        ("truyền hình 200 kênh", lambda p: A(p, "so_kenh") == 200, "numeric_attr"),
        ("gói miễn phí data tiktok", lambda p: "TikTok" in (A(p, "ung_dung_mien_phi") or []), "numeric_attr"),
        ("internet có wifi mesh", lambda p: p["category"] == "Internet cáp quang" and A(p, "wifi_mesh"), "numeric_attr"),
        ("gói đóng 1 năm", lambda p: A(p, "chu_ky") == "12 tháng", "numeric_attr"),
    ]:
        skus = where(fn)
        cs.append(case(q, skus, set_status(skus), cat))
    for q, skus, st in [
        ("con chỉ dùng zalo gọi video cho con cháu thôi gói nào rẻ", ["TT5"], "matched"),
        ("nhà em 3 tầng wifi tầng trên yếu lắm", ["NET500M", "NET1G", "COMBO-NT2"], "ambiguous"),
        ("cuối tuần này đi đà lạt 7 ngày đăng ký gói gì", ["W50"], "matched"),
        ("tháng sau đi hàn quốc du lịch cần data", ["RM-JPKR", "RM-ASIA"], "ambiguous"),
        ("đi công tác bên đức 2 tuần", ["RM-GLOBAL"], "matched"),
        ("mình làm sale gọi điện cho khách suốt ngày", ["V200", "V160"], "ambiguous"),
        ("công ty cần lắp mạng có ip tĩnh để chạy camera", ["NETDN"], "matched"),
        ("cả nhà 4 người muốn dùng chung một gói", ["GD300"], "matched"),
        ("mê xem ngoại hạng anh trên tivi", ["TVPREMIUM", "COMBO-NT2"], "ambiguous"),
        ("em là sinh viên cần lắp mạng ở trọ", ["NETSV"], "matched"),
        ("hay xem netflix trên điện thoại", ["MAX200"], "matched"),
        ("dùng data lúc nhiều lúc ít không muốn bị giới hạn theo ngày", ["TH30"], "matched"),
        ("chỉ cần mạng dùng trong hôm nay thôi", ["D10", "D15"], "ambiguous"),
        ("công ty cấp sim cho nhân viên cần hóa đơn đỏ", ["DN250"], "matched"),
    ]:
        cs.append(case(q, skus, st, "use_case"))
    for q, skus in [
        ("gói d90", ["D90", "D90-6T"]), ("gói d120", ["D120", "D120-12T"]),
        ("gói 120 nghìn", where(lambda p: p["price"] == 120000)),
        ("gói combo", where(lambda p: p["category"] == "Gói combo" and A(p, "doi_tuong") == "Cá nhân")),
        ("lắp cáp quang", where(lambda p: p["category"] == "Internet cáp quang" and A(p, "doi_tuong") != "Doanh nghiệp")),
        ("gói chuyển vùng quốc tế", where(lambda p: p["category"] == "Chuyển vùng quốc tế")),
        ("gói sinh viên", ["SV50", "NETSV"]),
    ]:
        cs.append(case(q, skus, "ambiguous", "ambiguous"))
    cs.append(case("v120 với d120 khác nhau chỗ nào", ["V120", "D120"], "ambiguous", "compare"))
    cs.append(case("so sánh cáp quang 300 với 500 mesh", ["NET300", "NET500M"], "ambiguous", "compare"))
    for q, prev_text, prev, skus, st in [
        ("có bản đóng 6 tháng không", "gói d90", ["D90"], ["D90-6T"], "matched"),
        ("loại nhiều data hơn thì sao", "gói d120", ["D120"], ["D150", "MAX200"], "ambiguous"),
        ("vậy có kèm mesh không", "cáp quang 300 mega", ["NET300"], ["NET500M"], "matched"),
        ("gói đó gọi ngoại mạng được bao nhiêu phút", "gói combo v160", ["V160"], ["V160"], "matched"),
        ("thế còn nhật bản", "gói chuyển vùng châu á", ["RM-ASIA"], ["RM-JPKR", "RM-ASIA"], "ambiguous"),
        ("có gói nào kèm truyền hình không", "cáp quang mesh 500 mega", ["NET500M"], ["COMBO-NT2"], "matched"),
        ("rẻ hơn chút được không", "gói max200", ["MAX200"], ["D150", "V160", "D120"], "ambiguous"),
        ("gói này có miễn phí tiktok không", "gói mxh70", ["MXH70"], ["MXH70"], "matched"),
    ]:
        cs.append(case(q, skus, st, "multi_turn", {"previous_text": prev_text, "previous_skus": prev}))
    for q in ["mật khẩu wifi nhà tôi là gì", "sao hôm nay mạng chậm thế", "chuyển cho tôi gặp nhân viên kỹ thuật",
              "kiểm tra giúp tôi cước tháng này bao nhiêu", "cho hỏi giá xăng hôm nay", "bạn tên là gì",
              "tôi muốn khiếu nại bị trừ tiền oan"]:
        cs.append(case(q, [], "out_of_scope", "out_of_scope"))
    for q in ["gói esim cho đồng hồ apple watch", "gói 5g không giới hạn dung lượng", "truyền hình vệ tinh k+ lắp chảo",
              "gói chuyển vùng châu phi", "sim số đẹp tứ quý 8"]:
        cs.append(case(q, [], "no_match", "no_match"))
    return cs


if __name__ == "__main__":
    prods = build_products()
    cases = build_cases(prods)
    write_demo("vienthong", DEMO, DEFS, [{k: v for k, v in p.items() if not k.startswith("_")} for p in prods], cases)
