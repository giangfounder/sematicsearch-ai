"""Provider giả lập offline (GEMINI_PROVIDER=fake) để test luồng không cần mạng.

- embed: vector băm từ âm tiết/bigram/trigram ký tự (không dấu) -> dense gần giống lexical.
  KHÔNG phản ánh chất lượng embedding thật; mọi con số độ chính xác phải đo bằng Gemini thật.
- generate_json: trả output trung tính (understand: chỉ chép câu; rerank: relevance theo trùng token);
  test có thể gắn handler riêng qua `handlers[call_type]` hoặc ép lỗi qua `fail[call_type]`.
"""
from __future__ import annotations

import asyncio
import re
import time
import zlib

import numpy as np

from app.gemini.pool import BaseGemini, GeminiError, l2_normalize
from app.text.normalize import basic_clean, strip_accents


def _feats(text: str) -> list[tuple[str, float]]:
    s = strip_accents(basic_clean(text))
    syl = s.split()
    feats = [(f"w:{w}", 1.0) for w in syl]
    feats += [(f"b:{a}_{b}", 1.0) for a, b in zip(syl, syl[1:])]
    padded = f" {s} "
    feats += [(f"c:{padded[i:i + 3]}", 0.3) for i in range(len(padded) - 2)]
    return feats


def hash_embed(text: str, dim: int) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    for f, w in _feats(text):
        h = zlib.crc32(f.encode("utf-8"))
        v[h % dim] += w if (h >> 16) & 1 else -w
    return l2_normalize(v)


class FakeGemini(BaseGemini):
    def __init__(self, settings):
        super().__init__(settings)
        self.handlers: dict = {}
        self.fail: dict[str, str] = {}  # call_type -> reason (timeout|error|rate_limited)
        self.delay_ms: dict[str, float] = {}
        self.calls: dict[str, int] = {}

    @property
    def provider(self) -> str:
        return "fake"

    async def _pre(self, call_type: str, timeout_ms: int) -> float:
        self._check_breaker(call_type)
        self.calls[call_type] = self.calls.get(call_type, 0) + 1
        d = self.delay_ms.get(call_type, 0)
        if d:
            if d >= timeout_ms:
                await asyncio.sleep(timeout_ms / 1000)
                self.breakers[call_type].fail()
                raise GeminiError("timeout", call_type)
            await asyncio.sleep(d / 1000)
        if call_type in self.fail:
            self.breakers[call_type].fail()
            raise GeminiError(self.fail[call_type], "forced by test")
        return time.perf_counter()

    async def embed(self, texts, task, *, call_type, timeout_ms, demo_id=0, model=None, dim=None):
        t0 = await self._pre(call_type, timeout_ms)
        dim = dim or self.s.embed_dim
        out = np.vstack([hash_embed(t, dim) for t in texts]) if texts else np.zeros((0, dim), np.float32)
        self.breakers[call_type].ok()
        self.usage.add(demo_id, call_type, model or "fake-embed", 0, 0, False, (time.perf_counter() - t0) * 1000)
        return out

    async def generate_json(self, *, system, contents, schema, call_type, timeout_ms, demo_id=0,
                            model=None, max_output_tokens=1024, temperature=0.0):
        t0 = await self._pre(call_type, timeout_ms)
        h = self.handlers.get(call_type)
        if h is not None:
            res = h(system=system, contents=contents, schema=schema)
            if asyncio.iscoroutine(res):
                res = await res
        elif call_type == "understand":
            res = self._understand(contents)
        elif call_type == "rerank":
            res = self._rerank(contents, schema)
        else:
            res = {}
        self.breakers[call_type].ok()
        self.usage.add(demo_id, call_type, model or "fake-llm", 0, 0, False, (time.perf_counter() - t0) * 1000)
        return res

    @staticmethod
    def _understand(contents: str) -> dict:
        m = re.search(r'Câu khách: "(.*)"', contents)
        q = m.group(1) if m else contents
        return {"intent": "find_product", "rewritten_query": q, "mentioned_products": [],
                "filters": {"attributes": []}}

    @staticmethod
    def _rerank(contents: str, schema: dict) -> dict:
        m = re.search(r'Khách hỏi: "(.*)"', contents)
        q = set(strip_accents(basic_clean(m.group(1) if m else "")).split())
        results = []
        for pid, line in re.findall(r"^\[(\d+)\] (.*)$", contents, flags=re.M):
            toks = set(strip_accents(basic_clean(line)).split())
            rel = len(q & toks) / max(1, len(q))
            results.append({"product_id": int(pid), "relevance": round(rel, 3),
                            "satisfies_constraints": True, "reason": line.split(" | ")[0]})
        return {"results": results}
