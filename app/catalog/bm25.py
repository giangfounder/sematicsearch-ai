"""BM25 nhỏ gọn trên numpy (inverted index), đủ nhanh cho vài nghìn tài liệu."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.n = len(docs)
        self.k1, self.b = k1, b
        lens = np.array([len(d) for d in docs], dtype=np.float32)
        avg = float(lens.mean()) if self.n else 1.0
        norm = k1 * (1 - b + b * lens / max(avg, 1e-6))
        post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for t, tf in Counter(d).items():
                post[t].append((i, tf))
        self.index: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for t, lst in post.items():
            ids = np.array([i for i, _ in lst], dtype=np.int32)
            tf = np.array([f for _, f in lst], dtype=np.float32)
            df = len(lst)
            idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
            self.index[t] = (ids, idf * tf * (k1 + 1) / (tf + norm[ids]))

    def scores(self, query: list[str]) -> np.ndarray:
        s = np.zeros(self.n, dtype=np.float32)
        for t in set(query):
            hit = self.index.get(t)
            if hit is not None:
                s[hit[0]] += hit[1]
        return s
