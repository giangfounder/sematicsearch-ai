"""Wrapper ghép 2 provider: chính (Gemini) + dự phòng (GPT, Meta Llama).

- LLM (understand/rerank/enrich/gen_eval): lỗi hết quota / 429 / breaker mở -> tự chuyển GPT.
  Kết quả JSON được provider dự phòng kiểm tra theo schema.
- Embedding: KHÔNG thể trộn không gian vector giữa 2 model. Do đó embed được điều hướng
  theo embed_model của demo: model nào thì gọi provider đó. Khi Gemini hết quota lúc
  ingest, job chuẩn bị đầy đủ vector mới rồi mới đổi embed_model của bảng (xem main.py).
"""
from __future__ import annotations

import logging
import asyncio
import time

from app.gemini.pool import BaseGemini, GeminiError
from app.gemini.openai_provider import TRANSIENT_REASONS

log = logging.getLogger("gemini.fallback")


class FallbackGemini(BaseGemini):
    def __init__(self, primary: BaseGemini, secondary: BaseGemini | None = None,
                 tertiary: BaseGemini | None = None):
        super().__init__(primary.s)
        self.primary = primary
        self.secondary = secondary
        self.tertiary = tertiary
        self.providers = [p for p in (primary, secondary, tertiary) if p is not None]
        self.usage = primary.usage
        for provider in self.providers:
            provider.usage = self.usage
        self.breakers = primary.breakers

    @property
    def provider(self) -> str:
        return "+".join(p.provider for p in self.providers)

    async def start(self) -> None:
        started = []
        try:
            for provider in self.providers:
                await provider.start()
                started.append(provider)
        except BaseException:
            await asyncio.gather(*(p.close() for p in reversed(started)), return_exceptions=True)
            raise

    async def close(self) -> None:
        results = await asyncio.gather(*(p.close() for p in reversed(self.providers)), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    def _use_gpt(self, model: str | None) -> bool:
        return bool(model) and model == self.s.openai_embed_model

    async def embed(self, texts, task, *, call_type, timeout_ms, demo_id=0, model=None, dim=None):
        target = self.secondary if self._use_gpt(model) else self.primary
        if target is None:
            raise GeminiError("unavailable", "GPT embedding provider chưa được cấu hình")
        return await target.embed(texts, task, call_type=call_type, timeout_ms=timeout_ms,
                                  demo_id=demo_id, model=model, dim=dim)

    async def generate_json(self, *, system, contents, schema, call_type, timeout_ms, demo_id=0,
                            model=None, max_output_tokens=1024, temperature=0.0) -> dict:
        deadline = time.monotonic() + timeout_ms / 1000
        for index, provider in enumerate(self.providers):
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining < 1:
                raise GeminiError("timeout", f"{call_type}: exhausted fallback deadline")
            try:
                return await asyncio.wait_for(provider.generate_json(
                    system=system, contents=contents, schema=schema, call_type=call_type,
                    timeout_ms=remaining, demo_id=demo_id, model=model if index == 0 else None,
                    max_output_tokens=max_output_tokens, temperature=temperature), remaining / 1000)
            except asyncio.TimeoutError:
                raise GeminiError("timeout", f"{call_type}: exhausted fallback deadline") from None
            except GeminiError as exc:
                if (exc.reason not in TRANSIENT_REASONS | {"authentication_error", "bad_output"}
                        or index == len(self.providers) - 1):
                    raise
                log.warning("%s: %s %s -> %s", call_type, provider.provider, exc.reason,
                            self.providers[index + 1].provider)

    def health(self) -> dict:
        return {
            "provider": self.provider,
            "breakers": {k: b.state for k, b in self.breakers.items()},
            "usage": self.usage.summary(),
            "primary": self.primary.health(),
            "fallback": self.secondary.health() if self.secondary else None,
            "tertiary": self.tertiary.health() if self.tertiary else None,
        }
