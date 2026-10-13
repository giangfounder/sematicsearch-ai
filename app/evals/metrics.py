"""Chỉ số đánh giá."""
from __future__ import annotations

import math

import numpy as np


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d), min(1.0, (c + r) / d)


def pct(xs: list[float], q: float) -> float | None:
    return round(float(np.percentile(xs, q)), 1) if xs else None


def fit_platt(x: list[float], y: list[int], iters: int = 200) -> tuple[float, float]:
    """Logistic 1 biến p = sigmoid(A x + B), Newton có điều chuẩn nhẹ (tránh A vô hạn khi tách hoàn toàn)."""
    X = np.asarray(x, dtype=np.float64)
    Y = np.asarray(y, dtype=np.float64)
    if len(X) < 4 or Y.min() == Y.max():
        return 10.0, -5.0
    # Platt: nhãn mềm chống quá khớp
    n1, n0 = Y.sum(), len(Y) - Y.sum()
    T = np.where(Y > 0, (n1 + 1) / (n1 + 2), 1 / (n0 + 2))
    w = np.array([1.0, 0.0])
    lam = 1e-3
    for _ in range(iters):
        z = w[0] * X + w[1]
        p = 1 / (1 + np.exp(-np.clip(z, -50, 50)))
        g = np.array([np.sum((p - T) * X) + lam * w[0], np.sum(p - T)])
        s = p * (1 - p)
        H = np.array([[np.sum(s * X * X) + lam, np.sum(s * X)], [np.sum(s * X), np.sum(s) + 1e-9]])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return float(w[0]), float(w[1])
