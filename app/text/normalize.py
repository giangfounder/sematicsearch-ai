"""Chuẩn hoá câu tiếng Việt (output ASR / chat): NFC, lowercase, bỏ dấu câu, bỏ từ đệm,
tạo bản không dấu và token (âm tiết + bigram)."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from app.config import DEFAULT_FILLERS

_PUNCT_RE = re.compile(r"[^\w\s.,/%+-]", re.UNICODE)
# dấu . , chỉ giữ khi nằm giữa 2 chữ số (9,8 tr ; 1.200.000)
_SEP_RE = re.compile(r"(?<!\d)[.,]|[.,](?!\d)")
_DASH_RE = re.compile(r"(?<!\d)[-/+]|[-/+](?!\d)")
_WS_RE = re.compile(r"\s+")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


@lru_cache(maxsize=20000)
def strip_accents(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", s)


def basic_clean(text: str) -> str:
    """lower + NFC + bỏ dấu câu (giữ số thập phân, khoảng 2-3, m2, %)."""
    s = nfc(text).lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SEP_RE.sub(" ", s)
    s = _DASH_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


@lru_cache(maxsize=64)
def _filler_re(fillers: tuple[str, ...]) -> re.Pattern:
    parts = sorted({basic_clean(f) for f in fillers if f.strip()}, key=len, reverse=True)
    if not parts:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?:(?<=\s)|^)(?:" + "|".join(re.escape(p) for p in parts) + r")(?=\s|$)")


def remove_fillers(s: str, extra: list[str] | None = None) -> str:
    fillers = tuple(DEFAULT_FILLERS + list(extra or []))
    out = _filler_re(fillers).sub(" ", s)
    out = _WS_RE.sub(" ", out).strip()
    # câu chỉ toàn từ đệm -> giữ nguyên để không thành rỗng
    return out or s


def normalize_query(text: str, extra_fillers: list[str] | None = None) -> tuple[str, str]:
    """Trả (câu chuẩn hoá có dấu, bản không dấu)."""
    s = remove_fillers(basic_clean(text), extra_fillers)
    return s, strip_accents(s)


def norm_text(text: str) -> str:
    """Chuẩn hoá cho dữ liệu catalog (không bỏ từ đệm)."""
    return basic_clean(text)


def syllables(s: str) -> list[str]:
    return [t for t in s.split(" ") if t]


def tokens(s: str) -> list[str]:
    """Âm tiết + bigram âm tiết."""
    syl = syllables(s)
    return syl + [f"{a}_{b}" for a, b in zip(syl, syl[1:])]
