"""Lượng tử hoá Int8 đối xứng theo từng vector: x ≈ q * scale, scale = max|x| / 127."""
from __future__ import annotations

import numpy as np


def quantize(vecs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vecs = np.atleast_2d(np.asarray(vecs, dtype=np.float32))
    scale = np.abs(vecs).max(axis=1) / 127.0
    scale[scale == 0] = 1.0
    q = np.clip(np.rint(vecs / scale[:, None]), -127, 127).astype(np.int8)
    return q, scale.astype(np.float32)


def dequantize(q: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return q.astype(np.float32) * np.asarray(scale, dtype=np.float32)[:, None]


def int8_cosine(q_int8: np.ndarray, q_scale: float, m_int8_as_f32: np.ndarray, m_scale: np.ndarray) -> np.ndarray:
    """Cosine xấp xỉ bằng tích vô hướng giá trị Int8 (m đã cast sang float32 một lần lúc nạp
    để dùng BLAS; giá trị vẫn là số nguyên Int8 nên kết quả đúng như phép nhân Int8)."""
    dots = m_int8_as_f32 @ q_int8.astype(np.float32)
    return dots * m_scale * q_scale
