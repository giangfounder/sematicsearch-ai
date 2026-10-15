"""Provider OpenAI-compatible (GPT) làm nguồn dự phòng khi Gemini hết quota.

Hỗ trợ mọi endpoint nói chuẩn OpenAI (api.openai.com, Azure OpenAI style, OpenRouter...).
Dùng httpx có sẵn, không thêm dependency mới. Mọi lỗi được chuyển về GeminiError để
tầng trên không cần biết về provider thứ hai. Key không bao giờ lộ ra log/exception.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
import numpy as np

from app.config import Settings
from app.gemini.pool import BaseGemini, GeminiError, l2_normalize, redact

log = logging.getLogger("openai")

# Nguyên nhân hợp lệ để chuyển từ Gemini sang GPT (và ngược lại ở wrapper).
TRANSIENT_REASONS = frozenset({"timeout", "rate_limited", "quota_exhausted",
                               "breaker_open", "unavailable", "error"})
# 5xx / network / timeout trong khi embedding vẫn bỏ qua (jobs vẫn coi đây là batch lỗi).
RETRYABLE_STATUS = (408, 429, 500, 502, 503, 504)


class OpenAICompatProvider(BaseGemini):
    """Nhóm client embedding + chat completions nói chuẩn OpenAI."""

    EMBED_BATCH = 100

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(settings)
        self._transport = transport
        self.http: httpx.AsyncClient | None = None
        self.cooldown: list[float] = []
        self._rr = 0
        self._doc_limiter = None
        if settings.openai_embed_rpm > 0:
            from app.ingest.vectors import RateLimiter

            self._doc_limiter = RateLimiter(settings.openai_embed_rpm)

    # ------------------------------------------------------------------ lifecycle
    @property
    def provider(self) -> str:
        return "gpt"

    async def start(self) -> None:
        keys = self.s.openai_keys
        if not keys:
            raise RuntimeError("OPENAI_API_KEY trống (GPT fallback không được bật)")
        self.http = httpx.AsyncClient(base_url=self.s.openai_base_url.rstrip("/"),
                                      timeout=httpx.Timeout(60.0, connect=5.0),
                                      transport=self._transport)
        self.cooldown = [0.0] * len(keys)

    async def close(self) -> None:
        if self.http is not None:
            await self.http.aclose()
            self.http = None

    # ------------------------------------------------------------------ key rotation
    def _pick(self, exclude: set[int]) -> int | None:
        now = time.monotonic()
        n = len(self.cooldown)
        for step in range(n):
            i = (self._rr + step) % n
            if i not in exclude and self.cooldown[i] <= now:
                self._rr = (i + 1) % n
                return i
        return None

    # ------------------------------------------------------------------ core call
    async def _post(self, call_type: str, demo_id: int, model: str, timeout_ms: int,
                    path: str, payload: dict, *, max_tries: int, json_mode: bool = True) -> tuple[httpx.Response, float]:
        """Gửi POST với xoay key + backoff. Trả về (response, ms). Đóng lỗi ra GeminiError."""
        b = self._check_breaker(call_type)
        keys = self.s.openai_keys
        if self.http is None or not keys:
            raise GeminiError("unavailable", "GPT provider chưa khởi tạo")
        tried: set[int] = set()
        last_err: GeminiError | None = None

        for attempt in range(max_tries):
            idx = self._pick(tried)
            if idx is None:
                # mọi key đang cooldown -> chờ 1 nhịp rồi thử lại lần cuối
                delay = max(0.0, min(self.cooldown) - time.monotonic()) if self.cooldown else 0.0
                if delay > 0.5:
                    last_err = GeminiError("quota_exhausted", "tất cả GPT key đang hết quota")
                    break
                await asyncio.sleep(delay)
                idx = self._pick(set())
                if idx is None:
                    break
            tried.add(idx)

            if self._doc_limiter is not None and path.endswith("/embeddings"):
                await self._doc_limiter.acquire(1)
            elif self.llm_limiter is not None and path.endswith("/chat/completions"):
                await self.llm_limiter.acquire(1)

            headers = {"Authorization": f"Bearer {keys[idx]}", "Content-Type": "application/json"}
            t0 = time.perf_counter()
            try:
                async with self.sem:
                    resp = await asyncio.wait_for(self.http.post(path, json=payload, headers=headers),
                                                  timeout=timeout_ms / 1000)
            except asyncio.TimeoutError:
                self.usage.error(call_type, "timeout")
                b.fail()
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                last_err = GeminiError("timeout", f"{call_type} > {timeout_ms}ms")
                continue
            except (httpx.TransportError, OSError) as e:
                self.usage.error(call_type, "transport")
                b.fail()
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                last_err = GeminiError("unavailable", type(e).__name__)
                continue

            ms = (time.perf_counter() - t0) * 1000
            code = resp.status_code
            if code in RETRYABLE_STATUS:
                self.usage.error(call_type, str(code))
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                if code in (500, 502, 503, 504, 408):
                    b.fail()
                    last_err = GeminiError("unavailable", f"OpenAI HTTP {code}")
                else:
                    # 429: key này đang bị giới hạn, xoay sang key khác / thử lại sau
                    self.cooldown[idx] = time.monotonic() + max(self.s.key_cooldown_s, 5.0)
                    last_err = GeminiError("rate_limited", "OpenAI HTTP 429; xoay key rồi thử lại")
                if attempt + 1 < max_tries:
                    await asyncio.sleep(min(2 ** attempt, 16) * 0.5)
                continue
            if code >= 400:
                b.fail()
                reason = "invalid_input" if code == 400 else "error"
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                raise GeminiError(reason, f"OpenAI HTTP {code}; {redact(resp.text)[:200]}") from None
            b.ok()
            return resp, ms

        b.fail()
        raise last_err or GeminiError("rate_limited", "không còn GPT key khả dụng")

    # ------------------------------------------------------------------ embeddings
    async def embed(self, texts, task, *, call_type, timeout_ms, demo_id=0, model=None, dim=None) -> np.ndarray:
        model = model or self.s.openai_embed_model
        dim = dim or self.s.embed_dim
        out: list[np.ndarray] = []
        for start in range(0, len(texts), self.EMBED_BATCH):
            chunk = texts[start:start + self.EMBED_BATCH]
            payload: dict = {"model": model, "input": list(chunk)}
            # text-embedding-3-* cho phép nén về đúng kích thước vector của demo (768),
            # nhờ đó index cũ và truy vấn mới cùng không gian.
            if model.startswith("text-embedding-3"):
                payload["dimensions"] = dim
            resp, ms = await self._post(call_type, demo_id, model, timeout_ms,
                                        "/embeddings", payload, max_tries=max(2, len(self.s.openai_keys) * 2))
            try:
                data = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
                vecs = np.array([d["embedding"] for d in data], dtype=np.float32)
            except (KeyError, TypeError, ValueError) as exc:
                raise GeminiError("bad_output", "GPT trả vector không hợp lệ") from exc
            if (vecs.shape != (len(chunk), dim) or not np.isfinite(vecs).all()
                    or np.any(np.linalg.norm(vecs, axis=1) == 0)):
                raise GeminiError("bad_output", f"embedding shape {vecs.shape}")
            self.usage.add(demo_id, call_type, model, sum(len(t) for t in chunk) // 4, 0, False, ms)
            out.append(vecs)
        return l2_normalize(np.vstack(out)) if out else np.zeros((0, dim), np.float32)

    # ------------------------------------------------------------------ LLM
    async def generate_json(self, *, system, contents, schema, call_type, timeout_ms, demo_id=0,
                            model=None, max_output_tokens=1024, temperature=0.0) -> dict:
        model = model or self.s.openai_llm_model
        online = call_type in ("understand", "rerank")
        max_tries = 2 if online else max(3, len(self.s.openai_keys) * 2)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": contents}]
        payload: dict = {"model": model, "messages": messages, "temperature": temperature,
                         "max_tokens": max_output_tokens, "response_format": {"type": "json_object"}}
        try:
            resp, ms = await self._post(call_type, demo_id, model, timeout_ms, "/chat/completions",
                                        payload, max_tries=max_tries)
        except GeminiError as e:
            # Một số gateway không hỗ trợ response_format -> thử lại bằng JSON tự cắt.
            if e.reason == "invalid_input":
                log.info("%s không hỗ trợ response_format, thử lại không có", model)
                payload.pop("response_format", None)
                resp, ms = await self._post(call_type, demo_id, model, timeout_ms, "/chat/completions",
                                            payload, max_tries=max_tries)
            else:
                raise
        try:
            j = resp.json()
            text = j["choices"][0]["message"]["content"] or ""
            u = j.get("usage") or {}
            self.usage.add(demo_id, call_type, model, int(u.get("prompt_tokens") or 0),
                           int(u.get("completion_tokens") or 0), False, ms)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GeminiError("bad_output", "GPT trả JSON không hợp lệ") from exc
        text = _strip_fences(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise GeminiError("bad_output", "GPT trả JSON không hợp lệ") from None


def _strip_fences(text: str) -> str:
    """Một số model bọc output trong ```json ... ``` dù yêu cầu JSON."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[: s.rfind("```")]
        s = s.strip()
        if s.startswith("json"):
            s = s[4:].strip()
    return s
