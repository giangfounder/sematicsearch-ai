"""Provider OpenAI-compatible (GPT) làm nguồn dự phòng khi Gemini hết quota.

Hỗ trợ API OpenAI và gateway có cùng giao thức /chat/completions, /embeddings.
Dùng httpx và kiểm tra JSON Schema. Mọi lỗi được chuyển về GeminiError để
tầng trên không cần biết về provider thứ hai. Key không bao giờ lộ ra log/exception.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import random

import httpx
import numpy as np
from jsonschema import Draft202012Validator, ValidationError, SchemaError

from app.config import Settings
from app.gemini.pool import BaseGemini, GeminiError, l2_normalize

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
        self.cooldown_reason: list[str] = []
        self._rr = 0
        self._doc_limiter = None
        if settings.openai_embed_rpm > 0:
            from app.ingest.vectors import RateLimiter

            self._doc_limiter = RateLimiter(settings.openai_embed_rpm)

    # ------------------------------------------------------------------ lifecycle
    @property
    def provider(self) -> str:
        return "gpt"

    @property
    def _keys(self) -> list[str]:
        return self.s.openai_keys

    @property
    def _base_url(self) -> str:
        return self.s.openai_base_url

    @property
    def _llm_model(self) -> str:
        return self.s.openai_llm_model

    async def start(self) -> None:
        keys = self._keys
        if not keys:
            raise RuntimeError(f"{self.provider}: API key chưa cấu hình")
        self.http = httpx.AsyncClient(base_url=self._base_url.rstrip("/"),
                                      timeout=httpx.Timeout(60.0, connect=5.0),
                                      transport=self._transport)
        self.cooldown = [0.0] * len(keys)
        self.cooldown_reason = [""] * len(keys)

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
        keys = self._keys
        if self.http is None or not keys:
            raise GeminiError("unavailable", f"{self.provider}: provider chưa khởi tạo")
        tried: set[int] = set()
        last_err: GeminiError | None = None

        deadline = time.monotonic() + timeout_ms / 1000
        for attempt in range(max_tries):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_err = GeminiError("timeout", f"{call_type}: request deadline exhausted")
                break
            idx = self._pick(tried)
            if idx is None:
                # mọi key đang cooldown -> chờ 1 nhịp rồi thử lại lần cuối
                delay = max(0.0, min(self.cooldown) - time.monotonic()) if self.cooldown else 0.0
                if delay > min(5.0, remaining) or call_type in ("understand", "rerank") and delay > 0:
                    reasons = set(self.cooldown_reason)
                    reason = next(iter(reasons)) if len(reasons) == 1 and next(iter(reasons)) else "rate_limited"
                    last_err = last_err or GeminiError(reason, f"{self.provider}: tất cả key đang tạm ngừng; kiểm tra quota/quyền API")
                    break
                await asyncio.sleep(delay)
                idx = self._pick(set())
                if idx is None:
                    break
            tried.add(idx)

            headers = {"Authorization": f"Bearer {keys[idx]}", "Content-Type": "application/json"}
            t0 = time.perf_counter()
            async def send():
                if self._doc_limiter is not None and path.endswith("/embeddings"):
                    await self._doc_limiter.acquire(1)
                elif self.llm_limiter is not None and path.endswith("/chat/completions"):
                    await self.llm_limiter.acquire(1)
                async with self.sem:
                    return await self.http.post(path, json=payload, headers=headers)
            try:
                resp = await asyncio.wait_for(send(), timeout=max(.001, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                self.usage.error(call_type, "timeout")
                b.fail()
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                last_err = GeminiError("timeout", f"{call_type} > {timeout_ms}ms")
                break
            except (httpx.TransportError, OSError) as e:
                self.usage.error(call_type, "transport")
                b.fail()
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                last_err = GeminiError("unavailable", type(e).__name__)
                continue

            ms = (time.perf_counter() - t0) * 1000
            code = resp.status_code
            try:
                api_error = resp.json().get("error", {})
                if not isinstance(api_error, dict):
                    api_error = {}
            except (ValueError, AttributeError):
                api_error = {}
            if code == 402:
                self.usage.error(call_type, "402")
                self.usage.add(demo_id, call_type, model, 0, 0, True, ms)
                self.cooldown[idx] = time.monotonic() + 3600
                self.cooldown_reason[idx] = "quota_exhausted"
                last_err = GeminiError("quota_exhausted", f"{self.provider} HTTP 402; kiểm tra billing/credits")
                continue
            if code in RETRYABLE_STATUS:
                self.usage.error(call_type, str(code))
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                if code in (500, 502, 503, 504, 408):
                    b.fail()
                    last_err = GeminiError("unavailable", f"{self.provider} HTTP {code}")
                else:
                    if api_error.get("code") in ("insufficient_quota", "credit_balance_exhausted") or api_error.get("type") == "insufficient_quota":
                        # Hết credits/billing: key này vô dụng tới khi nạp tiền, đừng thử lại phí.
                        self.cooldown[idx] = time.monotonic() + 3600.0
                        self.cooldown_reason[idx] = "quota_exhausted"
                        last_err = GeminiError("quota_exhausted", f"{self.provider}: hết credits/quota billing")
                    else:
                        try:
                            retry_after = float(resp.headers.get("retry-after", "0"))
                        except ValueError:
                            retry_after = 0.0
                        self.cooldown[idx] = time.monotonic() + max(self.s.key_cooldown_s, retry_after, .05)
                        self.cooldown_reason[idx] = "rate_limited"
                        last_err = GeminiError("rate_limited", f"{self.provider}: HTTP 429; xoay key rồi thử lại")
                if code != 429 and attempt + 1 < max_tries:
                    await asyncio.sleep(min(.25 * 2 ** attempt + random.uniform(0, .1), 4, max(0, deadline - time.monotonic())))
                continue
            if code in (401, 403):
                self.usage.error(call_type, str(code))
                self.usage.add(demo_id, call_type, model, 0, 0, True, ms)
                self.cooldown[idx] = time.monotonic() + 3600
                self.cooldown_reason[idx] = "authentication_error"
                last_err = GeminiError("authentication_error", f"{self.provider} HTTP {code}; kiểm tra quyền của API key")
                continue
            if code >= 400:
                b.fail()
                reason = "unsupported_format" if code == 400 and api_error.get("param") == "response_format" else "invalid_input" if code == 400 else "error"
                self.usage.add(demo_id, call_type, model, 0, 0, True, 0)
                # Never echo a provider body: it may contain credentials or input text.
                raise GeminiError(reason, f"{self.provider} HTTP {code}") from None
            b.ok()
            return resp, ms

        b.fail()
        raise last_err or GeminiError("rate_limited", f"{self.provider}: không còn key khả dụng")

    # ------------------------------------------------------------------ embeddings
    async def embed(self, texts, task, *, call_type, timeout_ms, demo_id=0, model=None, dim=None) -> np.ndarray:
        model = model or self.s.openai_embed_model
        dim = dim or self.s.embed_dim
        out: list[np.ndarray] = []
        for start in range(0, len(texts), self.EMBED_BATCH):
            chunk = texts[start:start + self.EMBED_BATCH]
            payload: dict = {"model": model, "input": list(chunk)}
            # Match dimensions, but NEVER compare these vectors with Gemini vectors.
            # Space compatibility requires a full staged model transition as well.
            if model.startswith("text-embedding-3"):
                payload["dimensions"] = dim
            resp, ms = await self._post(call_type, demo_id, model, timeout_ms,
                                        "/embeddings", payload, max_tries=max(2, len(self._keys) * 2))
            try:
                body = resp.json()
                if body.get("model") and body["model"] != model:
                    raise ValueError("unexpected embedding model")
                data = sorted(body["data"], key=lambda d: d["index"])
                if [d["index"] for d in data] != list(range(len(chunk))):
                    raise ValueError("invalid embedding indices")
                vecs = np.array([d["embedding"] for d in data], dtype=np.float32)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise GeminiError("bad_output", "GPT trả vector không hợp lệ") from exc
            if (vecs.shape != (len(chunk), dim) or not np.isfinite(vecs).all()
                    or np.any(np.linalg.norm(vecs, axis=1) == 0)):
                raise GeminiError("bad_output", f"embedding shape {vecs.shape}")
            self.usage.add(demo_id, call_type, model, sum(len(t) for t in chunk) // 4, 0, False, ms)
            out.append(vecs)
        return l2_normalize(np.vstack(out)) if out else np.zeros((0, dim), np.float32)

    # ------------------------------------------------------------------ LLM
    def _chat_payload(self, model, messages, schema, temperature, max_output_tokens) -> dict:
        return {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_output_tokens, "response_format": {"type": "json_object"}}

    def _completion(self, body: dict) -> tuple[str, int, int]:
        choice = body["choices"][0]
        if choice.get("finish_reason") in ("length", "content_filter") or choice["message"].get("refusal"):
            raise ValueError("incomplete or refused output")
        usage = body.get("usage") or {}
        return (choice["message"]["content"] or "", int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0))

    async def generate_json(self, *, system, contents, schema, call_type, timeout_ms, demo_id=0,
                            model=None, max_output_tokens=1024, temperature=0.0) -> dict:
        deadline = time.monotonic() + timeout_ms / 1000
        model = model or self._llm_model
        online = call_type in ("understand", "rerank")
        max_tries = 2 if online else max(3, len(self._keys) * 2)
        instructions = system + "\nReturn exactly one JSON object matching this JSON Schema. Do not include markdown.\n" + json.dumps(schema, ensure_ascii=False)
        messages = [{"role": "system", "content": instructions}, {"role": "user", "content": contents}]
        payload = self._chat_payload(model, messages, schema, temperature, max_output_tokens)
        try:
            resp, ms = await self._post(call_type, demo_id, model, timeout_ms, "/chat/completions",
                                        payload, max_tries=max_tries)
        except GeminiError as e:
            # Một số gateway không hỗ trợ response_format -> thử lại bằng JSON tự cắt.
            if e.reason == "unsupported_format":
                log.info("%s không hỗ trợ response_format, thử lại không có", model)
                payload.pop("response_format", None)
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining < 1:
                    raise GeminiError("timeout", "JSON format retry exhausted request deadline") from None
                resp, ms = await self._post(call_type, demo_id, model, remaining, "/chat/completions",
                                            payload, max_tries=max_tries)
            else:
                raise
        try:
            text, inp, out = self._completion(resp.json())
            self.usage.add(demo_id, call_type, model, inp, out, False, ms)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            self.usage.error(call_type, "bad_output")
            raise GeminiError("bad_output", f"{self.provider}: JSON không hợp lệ") from None
        try:
            output = json.loads(_strip_fences(text), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite number")))
            if not isinstance(output, dict):
                raise ValueError("JSON object required")
            Draft202012Validator(schema).validate(output)
            return output
        except (ValueError, TypeError, AttributeError, ValidationError, SchemaError):
            self.usage.error(call_type, "bad_output")
            raise GeminiError("bad_output", f"{self.provider}: JSON không khớp cấu trúc yêu cầu") from None

    def health(self) -> dict:
        return {**super().health(), "available_keys": sum(t <= time.monotonic() for t in self.cooldown),
                "configured_keys": len(self.cooldown),
                "cooldown_reasons": [r for t, r in zip(self.cooldown, self.cooldown_reason) if t > time.monotonic()]}


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
