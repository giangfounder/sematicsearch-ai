"""Client Gemini dùng chung: xoay key khi 429, timeout riêng từng loại call, circuit breaker,
giới hạn đồng thời, đếm token. Key không bao giờ xuất hiện trong log/exception trả ra ngoài."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import httpx

from app.config import Settings

log = logging.getLogger("gemini")
# Gemini từ chối deadline < 10s (400 INVALID_ARGUMENT). Deadline gửi server >= 10s;
# timeout ngắn thật sự do client cắt bằng asyncio.wait_for trong _call.
SERVER_MIN_DEADLINE_MS = 10000
_RETRY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"](\d+(?:\.\d+)?)s")
_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|AQ\.[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z_\-]{20,}")


def redact(s: str) -> str:
    return _KEY_RE.sub("***", s or "")


class GeminiError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {redact(detail)[:300]}")
        self.reason = reason  # timeout | rate_limited | breaker_open | error | bad_output


@dataclass
class Breaker:
    failures_to_open: int
    open_seconds: float
    fails: int = 0
    opened_at: float = 0.0

    def allow(self) -> bool:
        if self.fails < self.failures_to_open:
            return True
        return time.monotonic() - self.opened_at >= self.open_seconds  # half-open

    def ok(self) -> None:
        self.fails = 0

    def fail(self) -> None:
        self.fails += 1
        if self.fails >= self.failures_to_open:
            self.opened_at = time.monotonic()

    @property
    def state(self) -> str:
        if self.fails < self.failures_to_open:
            return "closed"
        return "half_open" if self.allow() else "open"


@dataclass
class Usage:
    """Bộ đếm RAM; flush định kỳ vào bảng gemini_usage."""
    pending: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0, 0]))
    totals: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0, 0]))
    latencies: dict = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=500)))
    error_codes: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))

    def error(self, call_type: str, code: str) -> None:
        self.error_codes[call_type][code] += 1

    def add(self, demo_id: int, call_type: str, model: str, inp: int, out: int, err: bool, ms: float) -> None:
        for d in (self.pending, self.totals):
            row = d[(demo_id or 0, call_type, model)]
            row[0] += 1
            row[1] += inp
            row[2] += out
            row[3] += int(err)
        if not err:
            self.latencies[call_type].append(ms)

    def drain(self) -> dict:
        p, self.pending = self.pending, defaultdict(lambda: [0, 0, 0, 0])
        return p

    def summary(self) -> dict:
        by_type: dict = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0})
        for (_, ct, _m), (c, i, o, e) in self.totals.items():
            r = by_type[ct]
            r["calls"] += c
            r["input_tokens"] += i
            r["output_tokens"] += o
            r["errors"] += e
        for ct, lat in self.latencies.items():
            if lat:
                arr = np.array(lat)
                by_type[ct]["p50_ms"] = round(float(np.percentile(arr, 50)), 1)
                by_type[ct]["p95_ms"] = round(float(np.percentile(arr, 95)), 1)
                by_type[ct]["mean_ms"] = round(float(np.mean(arr)), 1)
        for ct, codes in self.error_codes.items():
            by_type[ct]["error_codes"] = dict(codes)
        return dict(by_type)


def l2_normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    if m.ndim == 1:
        n = np.linalg.norm(m)
        return m / n if n > 0 else m
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


class BaseGemini:
    """Giao diện chung cho provider thật và giả."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.usage = Usage()
        self.breakers = {
            ct: Breaker(settings.breaker_failures, settings.breaker_open_s)
            for ct in ("understand", "embed_query", "rerank", "embed_doc", "enrich", "gen_eval")
        }
        self.sem = asyncio.Semaphore(settings.gemini_max_concurrency)
        self.doc_sem = asyncio.Semaphore(max(1, settings.embed_concurrency))
        # giới hạn request LLM/phút (0 = tắt). Dùng khi chạy evaluate trên free tier để không dính 429
        self.llm_limiter = None
        if settings.llm_rpm_limit > 0:
            from app.ingest.vectors import RateLimiter

            self.llm_limiter = RateLimiter(settings.llm_rpm_limit)

    @property
    def provider(self) -> str:
        return "base"

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def embed(self, texts: list[str], task: str, *, call_type: str, timeout_ms: int,
                    demo_id: int = 0, model: str | None = None, dim: int | None = None) -> np.ndarray:
        raise NotImplementedError

    async def generate_json(self, *, system: str, contents: str, schema: dict, call_type: str,
                            timeout_ms: int, demo_id: int = 0, model: str | None = None,
                            max_output_tokens: int = 1024, temperature: float = 0.0) -> dict:
        raise NotImplementedError

    def health(self) -> dict:
        return {
            "provider": self.provider,
            "breakers": {k: b.state for k, b in self.breakers.items()},
            "usage": self.usage.summary(),
        }

    def _check_breaker(self, call_type: str) -> Breaker:
        b = self.breakers.setdefault(call_type, Breaker(self.s.breaker_failures, self.s.breaker_open_s))
        if not b.allow():
            raise GeminiError("breaker_open", call_type)
        return b


class GeminiPool(BaseGemini):
    """Provider thật qua SDK google-genai (async)."""

    EMBED_BATCH = 100

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.clients: list = []
        self.cooldown: list[float] = []
        self._rr = 0

    @property
    def provider(self) -> str:
        return "gemini"

    async def start(self) -> None:
        from google import genai
        from google.genai import types

        keys = self.s.gemini_keys
        if not keys:
            raise RuntimeError("GEMINI_API_KEY trống (hoặc đặt GEMINI_PROVIDER=fake để chạy offline)")
        for k in keys:
            c = genai.Client(
                api_key=k,
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            )
            self.clients.append(c.aio)
        self.cooldown = [0.0] * len(self.clients)

    async def close(self) -> None:
        for c in self.clients:
            try:
                await c.aclose()
            except Exception:  # noqa: BLE001
                pass

    def _pick(self, exclude: set[int]) -> int | None:
        now = time.monotonic()
        n = len(self.clients)
        for step in range(n):
            i = (self._rr + step) % n
            if i not in exclude and self.cooldown[i] <= now:
                self._rr = (i + 1) % n
                return i
        return None

    async def _call(self, call_type: str, demo_id: int, model: str, timeout_ms: int, fn, max_key_tries: int):
        from google.genai import errors

        b = self._check_breaker(call_type)
        tried: set[int] = set()
        last_err: GeminiError | None = None
        backoff = max_key_tries > 2  # call offline: chờ rồi thử lại thay vì bỏ cuộc
        for attempt in range(max_key_tries):
            idx = self._pick(set() if backoff else tried)
            if idx is None:
                if not backoff or not self.cooldown:
                    break
                delay = max(0.0, min(self.cooldown) - time.monotonic())
                if delay > 300:
                    raise GeminiError("quota_exhausted", "tất cả API key đang hết quota; vector đã lưu được giữ lại")
                await asyncio.sleep(delay)
                idx = self._pick(set())
                if idx is None:
                    continue
            tried.add(idx)
            t0 = time.perf_counter()
            try:
                async with self.sem:
                    resp = await asyncio.wait_for(fn(self.clients[idx]), timeout=timeout_ms / 1000)
                ms = (time.perf_counter() - t0) * 1000
                b.ok()
                return resp, ms
            except asyncio.TimeoutError:
                self.usage.error(call_type, "timeout")
                last_err = GeminiError("timeout", f"{call_type} > {timeout_ms}ms")
                b.fail()
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                if backoff and attempt + 1 < max_key_tries:
                    await asyncio.sleep(min(2 ** attempt, 16) + random.uniform(0, 0.5))
                    continue
                raise last_err from None
            except errors.APIError as e:  # noqa: PERF203
                code = getattr(e, "code", None)
                self.usage.error(call_type, str(code))
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                if code == 429:
                    m = _RETRY_RE.search(str(e))
                    delay = float(m.group(1)) + 1 if m else 2 ** min(attempt + 1, 5)
                    if delay > 300:  # quota theo ngày: key này vô dụng tới khi reset
                        self.cooldown[idx] = time.monotonic() + delay
                        last_err = GeminiError("quota_exhausted", f"{call_type}: hết quota ngày, reset sau {delay / 3600:.1f} giờ")
                        if len(tried) >= len(self.clients):
                            raise last_err from None
                        continue
                    self.cooldown[idx] = time.monotonic() + max(delay, self.s.key_cooldown_s)
                    last_err = GeminiError("rate_limited", "Gemini HTTP 429; chờ quota rồi thử lại")
                    if backoff:
                        log.info("%s 429, chờ %.0fs (lần %d)", call_type, delay, attempt + 1)
                        await asyncio.sleep(delay)
                    continue
                if code in (408, 500, 502, 503, 504) and backoff:
                    b.fail()
                    last_err = GeminiError("unavailable", f"Gemini HTTP {code}; các batch đã lưu vẫn an toàn")
                    if attempt + 1 < max_key_tries:
                        await asyncio.sleep(min(2 ** attempt, 16) + random.uniform(0, 0.5))
                        continue
                    raise last_err from None
                b.fail()
                reason = "invalid_input" if code == 400 else "error"
                raise GeminiError(reason, f"Gemini HTTP {code}; request bị từ chối") from None
            except (httpx.TransportError, OSError) as e:
                self.usage.error(call_type, "transport")
                b.fail()
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                last_err = GeminiError("unavailable", type(e).__name__)
                if backoff and attempt + 1 < max_key_tries:
                    await asyncio.sleep(min(2 ** attempt, 16) + random.uniform(0, 0.5))
                    continue
                raise last_err from None
            except Exception as e:  # noqa: BLE001
                b.fail()
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                raise GeminiError("error", type(e).__name__) from None
        b.fail()
        raise last_err or GeminiError("rate_limited", "no key available")

    async def embed(self, texts, task, *, call_type, timeout_ms, demo_id=0, model=None, dim=None):
        from google.genai import types

        model = model or self.s.gemini_embed_model
        dim = dim or self.s.embed_dim
        online = call_type == "embed_query"
        out: list[np.ndarray] = []
        for start in range(0, len(texts), self.EMBED_BATCH):
            chunk = texts[start:start + self.EMBED_BATCH]
            cfg = types.EmbedContentConfig(
                task_type=task, output_dimensionality=dim,
                http_options=types.HttpOptions(timeout=max(timeout_ms, SERVER_MIN_DEADLINE_MS)),
            )

            async def fn(c, chunk=chunk, cfg=cfg):
                return await c.models.embed_content(model=model, contents=chunk, config=cfg)

            resp, ms = await self._call(call_type, demo_id, model, timeout_ms, fn,
                                        max_key_tries=2 if online else max(8, len(self.clients) * 3))
            self.usage.add(demo_id, call_type, model, sum(len(t) for t in chunk) // 4, 0, False, ms)
            try:
                vecs = np.array([e.values for e in resp.embeddings], dtype=np.float32)
            except (TypeError, ValueError) as exc:
                raise GeminiError("bad_output", "embedding response is missing or invalid") from exc
            if (vecs.shape != (len(chunk), dim) or not np.isfinite(vecs).all()
                    or np.any(np.linalg.norm(vecs, axis=1) == 0)):
                raise GeminiError("bad_output", f"embedding shape {vecs.shape}")
            out.append(vecs)
        return l2_normalize(np.vstack(out)) if out else np.zeros((0, dim), np.float32)

    async def generate_json(self, *, system, contents, schema, call_type, timeout_ms, demo_id=0,
                            model=None, max_output_tokens=1024, temperature=0.0):
        from google.genai import types

        model = model or self.s.gemini_llm_model
        kw = {}
        if self.s.gemini_thinking_level and not model.startswith("gemini-2."):
            kw["thinking_config"] = types.ThinkingConfig(thinking_level=self.s.gemini_thinking_level.upper())
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=schema,
            http_options=types.HttpOptions(timeout=max(timeout_ms, SERVER_MIN_DEADLINE_MS)),
            **kw,
        )

        async def fn(c):
            return await c.models.generate_content(model=model, contents=contents, config=cfg)

        online = call_type in ("understand", "rerank")
        if self.llm_limiter is not None:
            await self.llm_limiter.acquire(1)
        resp, ms = await self._call(call_type, demo_id, model, timeout_ms, fn,
                                    max_key_tries=2 if online else max(8, len(self.clients) * 3))
        um = resp.usage_metadata
        self.usage.add(demo_id, call_type, model, (um.prompt_token_count or 0) if um else 0,
                       ((um.candidates_token_count or 0) + (um.thoughts_token_count or 0)) if um else 0, False, ms)
        text = resp.text or ""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise GeminiError("bad_output", "Gemini trả JSON không hợp lệ") from None


def make_gemini(settings: Settings) -> BaseGemini:
    if settings.gemini_provider == "fake":
        from app.gemini.fake import FakeGemini

        primary: BaseGemini = FakeGemini(settings)
    else:
        primary = GeminiPool(settings)
    if settings.gpt_enabled:
        from app.gemini.fallback import FallbackGemini
        from app.gemini.openai_provider import OpenAICompatProvider

        return FallbackGemini(primary, OpenAICompatProvider(settings))
    return primary
