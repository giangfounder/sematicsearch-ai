"""Công cụ dựng seed: sinh aliases/use_cases/sample_questions theo mẫu (dùng để EMBED) và eval_cases
theo mẫu KHÁC + nhiễu ASR (dùng để ĐO). Hai bộ mẫu tách biệt để tránh "học tủ"."""
from __future__ import annotations

import json
import random
import unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent

PHONETIC = {
    "samsung": ["sam sung", "sam xung", "xam sung"], "iphone": ["ai phôn", "ai phone", "ai phôn"],
    "apple": ["áp pồ", "táo"], "panasonic": ["pa na sô níc", "pana"], "toshiba": ["tô si ba", "tô xi ba"],
    "daikin": ["đai kin", "đại kim"], "lg": ["eo gi", "lờ gờ", "en gi"], "sony": ["sô ni", "xô ni"],
    "xiaomi": ["xao mi", "si ao mi"], "oppo": ["óp pô", "ốp pồ"], "casper": ["cát pơ", "cát xpơ"],
    "aqua": ["a qua", "a kua"], "electrolux": ["e léc trô lúc", "ê léc tơ rô lúc"], "sharp": ["sáp", "sạp"],
    "hitachi": ["hi ta chi", "hít ta chi"], "tcl": ["tê xê eo", "ti xi eo"], "galaxy": ["ga la xi", "ga lắc xi"],
    "redmi": ["rét mi", "red mi"], "reno": ["rê nô", "ri nô"], "inverter": ["in vơ tơ", "inh vớt tơ"],
    "qled": ["kiu led", "qui lét"], "oled": ["ô lét", "ô led"], "side by side": ["sai bai sai", "side bai side"],
    "pro max": ["pờ rô mác", "pro mác"], "ultra": ["un tra", "ân tra"],
}
TONE_SWAP = {"ạ": "ả", "ả": "ã", "ã": "ạ", "á": "à", "à": "á", "ị": "ỉ", "ỉ": "ĩ", "ĩ": "ị", "ó": "ỏ", "ỏ": "õ",
             "ọ": "ỏ", "ú": "ủ", "ủ": "ũ", "ụ": "ủ", "é": "ẻ", "ẻ": "ẽ", "ẹ": "ẻ", "ấ": "ầ", "ầ": "ẩ", "ậ": "ẩ",
             "ế": "ề", "ề": "ể", "ệ": "ể", "ố": "ồ", "ồ": "ổ", "ộ": "ổ", "ớ": "ờ", "ờ": "ở", "ợ": "ở", "ứ": "ừ",
             "ừ": "ử", "ự": "ử", "ắ": "ằ", "ằ": "ẳ", "ặ": "ẳ"}
DIGIT_WORDS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
FILLERS = ["dạ", "ừm", "alo", "dạ cho em hỏi", "ờ", "chị ơi", "à", "dạ vâng", "em hỏi chút"]


def strip_accents(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def num_words(n: float) -> str:
    """Số -> chữ kiểu nói (55 -> 'năm lăm', 236 -> 'hai trăm ba sáu', 1.5 -> 'một rưỡi')."""
    if n != int(n):
        return f"{num_words(int(n))} rưỡi" if abs(n - int(n) - 0.5) < 1e-9 else str(n)
    n = int(n)
    if n < 10:
        return DIGIT_WORDS[n]
    if n < 20:
        return "mười" + ("" if n == 10 else " " + ("lăm" if n % 10 == 5 else DIGIT_WORDS[n % 10]))
    if n < 100:
        t, u = divmod(n, 10)
        return f"{DIGIT_WORDS[t]} mươi" if u == 0 else f"{DIGIT_WORDS[t]} " + ("lăm" if u == 5 else "mốt" if u == 1 else DIGIT_WORDS[u])
    if n < 1000:
        h, r = divmod(n, 100)
        if r == 0:
            return f"{DIGIT_WORDS[h]} trăm"
        if r < 10:
            return f"{DIGIT_WORDS[h]} trăm linh {DIGIT_WORDS[r]}"
        return f"{DIGIT_WORDS[h]} trăm {num_words(r)}"
    return str(n)


def phonetic(text: str, rnd: random.Random) -> str:
    low = text.lower()
    for k in sorted(PHONETIC, key=len, reverse=True):
        if k in low:
            low = low.replace(k, rnd.choice(PHONETIC[k]))
    return low


def tone_noise(text: str, rnd: random.Random, rate: float = 0.25) -> str:
    out = []
    for w in text.split():
        if rnd.random() < rate:
            w = "".join(TONE_SWAP.get(ch, ch) for ch in w)
        out.append(w)
    return " ".join(out)


def money_words(v: float) -> str:
    tr = v / 1e6
    if tr >= 1000:
        ty = tr / 1000
        whole = int(ty)
        frac = round((ty - whole) * 10)
        return f"{num_words(whole)} tỷ" + (f" {DIGIT_WORDS[frac]}" if frac else "")
    whole = int(tr)
    frac = round((tr - whole) * 10)
    return f"{num_words(whole)} triệu" + (" rưỡi" if frac == 5 else f" {DIGIT_WORDS[frac]}" if frac else "")


def write_demo(slug: str, demo: dict, defs: list[dict], products: list[dict], cases: list[dict], seed: int = 11) -> None:
    rnd = random.Random(seed)
    by_cat: dict[str, list[dict]] = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)
    for lst in by_cat.values():
        rnd.shuffle(lst)
        k = round(len(lst) * 0.4)
        for j, c in enumerate(lst):
            c["split"] = "dev" if j < k else "test"
            c.setdefault("source", "manual")
    skus = {p["sku"] for p in products}
    for c in cases:
        bad = [s for s in c["expected_skus"] + (c.get("context") or {}).get("previous_skus", []) if s not in skus]
        assert not bad, (slug, c["query"], bad)
    # câu eval không được trùng câu hỏi mẫu
    sq = {strip_accents(q.lower()) for p in products for q in p["sample_questions"]}
    for c in cases:
        assert strip_accents(c["query"].lower()) not in sq, c["query"]
    d = OUT / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "demo.json").write_text(json.dumps({"demo": demo, "definitions": defs, "products": products},
                                            ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "eval_cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    cnt: dict[str, int] = {}
    for c in cases:
        cnt[c["category"]] = cnt.get(c["category"], 0) + 1
    print(f"{slug}: {len(products)} sản phẩm, {len(cases)} eval cases {cnt}")


def case(query: str, skus: list[str], status: str, category: str, ctx: dict | None = None) -> dict:
    c = {"query": query, "expected_skus": skus, "expected_status": status, "category": category}
    if ctx:
        c["context"] = ctx
    return c


def per_product_cases(products: list[dict], rnd: random.Random) -> list[dict]:
    """2 câu / sản phẩm: (tên hoặc alias) + (ASR hoặc không dấu), luân phiên để phủ đều."""
    out = []
    for i, p in enumerate(products):
        sp = p["_spoken"]  # cách gọi tự nhiên, đủ phân biệt
        fill = rnd.choice(FILLERS)
        if i % 2 == 0:
            out.append(case(f"{fill} {sp} còn hàng không", [p["sku"]], "matched", "name"))
        else:
            out.append(case(f"{rnd.choice(['bên mình có', 'shop có bán', 'cho mình hỏi'])} {p['_alias_q']} không",
                            [p["sku"]], "matched", "alias"))
        if i % 3 == 2:
            q = strip_accents(f"{p['_spoken2']} gia sao")
            out.append(case(q, [p["sku"]], "matched", "no_accent"))
        else:
            q = tone_noise(phonetic(p["_spoken_asr"], rnd), rnd)
            out.append(case(f"{rnd.choice(FILLERS)} {q} ạ", [p["sku"]], "matched", "asr"))
    return out


def set_status(skus: list[str]) -> str:
    return "matched" if len(skus) == 1 else "ambiguous" if skus else "no_match"
