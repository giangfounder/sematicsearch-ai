"""Chuyển số đọc bằng chữ (output ASR) sang chữ số.

"mười lăm triệu" -> "15 triệu", "chín triệu rưỡi" -> "9 triệu rưỡi" (rưỡi xử lý ở rules),
"bốn ba inch" -> "43 inch", "hai ba triệu" -> "2-3 triệu" (2 chữ số liên tiếp: x, x+1 = khoảng).
Chỉ đổi khi cụm số có >= 2 từ, hoặc 1 từ đứng ngay trước 1 đơn vị đã biết, để không phá
"năm" (năm học), "ba" (bố)...
"""
from __future__ import annotations

DIGITS = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "lăm": 5,
    "nhăm": 5, "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9,
}
NUM_WORDS = set(DIGITS) | {"mười", "mươi", "trăm", "linh", "lẻ"}

BASE_UNITS = {
    "triệu", "tr", "củ", "chai", "tỷ", "tỉ", "nghìn", "ngàn", "k", "trăm", "đồng", "vnd",
    "inch", "in", "lít", "cửa", "cánh", "gb", "tb", "kg", "m2", "mét", "phòng", "tầng",
    "năm", "tháng", "ngày", "w", "hp", "ngựa", "chiếc", "cái",
}


def _parse_run(toks: list[str]) -> str | None:
    """Parse 1 cụm từ số -> chuỗi số (có thể là khoảng 'a-b'). None nếu không hợp lệ."""
    if len(toks) == 2 and toks[0] in DIGITS and toks[1] in DIGITS:
        a, b = DIGITS[toks[0]], DIGITS[toks[1]]
        if toks[0] in ("lăm", "nhăm", "mốt"):
            return None
        if b == a + 1:
            return f"{a}-{b}"
        if a >= 1:
            return str(a * 10 + b)
    value, pending, last = 0, None, None
    for t in toks:
        if t in DIGITS:
            d = DIGITS[t]
            if last in ("mươi", "mười", "linh", "lẻ"):
                value += d
            elif last == "trăm":
                value += d * 10  # "một trăm hai" = 120
            elif pending is not None:
                return None
            else:
                pending = d
        elif t == "mười":
            if pending is not None:
                return None
            value += 10
        elif t == "mươi":
            if pending is None:
                return None
            value += pending * 10
            pending = None
        elif t == "trăm":
            value += (pending if pending is not None else 1) * 100
            pending = None
        elif t in ("linh", "lẻ"):
            if last != "trăm":
                return None
        last = t
    if pending is not None:
        value += pending
    return str(value)


def spoken_to_digits(text: str, extra_units: set[str] | None = None) -> str:
    units = BASE_UNITS | (extra_units or set())
    toks = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] in NUM_WORDS and toks[i] not in ("mươi", "linh", "lẻ"):
            j = i
            while j < len(toks) and toks[j] in NUM_WORDS:
                j += 1
            # "năm" cuối cụm (không sau linh/lẻ) là đơn vị năm: "hai năm", "mười năm" (25 phải đọc "hai lăm")
            if j - i >= 2 and toks[j - 1] == "năm" and toks[j - 2] not in ("linh", "lẻ"):
                j -= 1
            run = toks[i:j]
            nxt = toks[j] if j < len(toks) else ""
            prev = out[-1] if out else ""
            convertible = (
                len(run) >= 2
                or nxt in units
                or prev in ("giá", "tầm", "khoảng", "dưới", "trên", "từ", "đến", "tới", "hơn", "tỷ", "tỉ", "triệu", "tr", "củ")
            )
            if convertible and not (len(run) == 1 and run[0] == "năm" and nxt in ("nay", "ngoái", "sau", "trước")):
                parsed = _parse_run(run)
                if parsed is not None:
                    out.append(parsed)
                    i = j
                    continue
            out.extend(run)
            i = j
            continue
        out.append(toks[i])
        i += 1
    return " ".join(out)
