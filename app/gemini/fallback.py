"""Wrapper ghép 2 provider: chính (Gemini) + dự phòng (GPT).

- LLM (understand/rerank/enrich/gen_eval): lỗi hết quota / 429 / breaker mở -> tự chuyển GPT.
  An toàn tuyệt đối vì kết quả chỉ là text/JSON, không phụ thuộc không gian vector.
- Embedding: KHÔNG thể trộn không gian vector giữa 2 model. Do đó embed được điều hướng
  theo embed_model của demo: model nào thì gọi provider đó. Khi Gemini hết quota lúc
  ingest, lớp job sẽ đổi embed_model của bảng sang model GPT và embed lại (xem main.py).
"""
from __future__ import annotations

import logging

from app.gemini.pool import BaseGemini, GeminiError
from app.gemini.openai_provider import TRANSIENT_REASONS

log = logging.getLogger("gemini.fallback")


class FallbackGemini(BaseGemini):
    def __init__(self, primary: BaseGemini, secondary: BaseGemini):
        super().__init__(primary.s)
        self.primary = primary
        self.secondary = secondary
        # Gộp bộ đếm để /v1/admin/usage + flush gemini_usage vẫn ra một bảng duy nhất.
        self.usage = primary.usage
        secondary.usage = primary.usage
        self.breakers = primary.breakers

    @property
    def provider(self) -> str:
        return f"{self.primary.provider}+{self.secondary.provider}"

    async def start(self) -> None:
        await self.primary.start()
        await self.secondary.start()

    async def close(self) -> None:
        try:
            await self.secondary.close()
        finally:
            await self.primary.close()

    def _use_gpt(self, model: str | None) -> bool:
        return bool(model) and model == self.s.openai_embed_model

    async def embed(self, texts, task, *, call_type, timeout_ms, demo_id=0, model=None, dim=None):
        target = self.secondary if self._use_gpt(model) else self.primary
        return await target.embed(texts, task, call_type=call_type, timeout_ms=timeout_ms,
                                  demo_id=demo_id, model=model, dim=dim)

    async def generate_json(self, *, system, contents, schema, call_type, timeout_ms, demo_id=0,
                            model=None, max_output_tokens=1024, temperature=0.0) -> dict:
        try:
            return await self.primary.generate_json(system=system, contents=contents, schema=schema,
                                                    call_type=call_type, timeout_ms=timeout_ms,
                                                    demo_id=demo_id, model=model,
                                                    max_output_tokens=max_output_tokens,
                                                    temperature=temperature)
        except GeminiError as e:
            if e.reason not in TRANSIENT_REASONS:
                raise
            log.warning("%s: Gemini %s -> chuyển sang GPT", call_type, e.reason)
            return await self.secondary.generate_json(system=system, contents=contents, schema=schema,
                                                      call_type=call_type, timeout_ms=timeout_ms,
                                                      demo_id=demo_id, model=None,
                                                      max_output_tokens=max_output_tokens,
                                                      temperature=temperature)

    def health(self) -> dict:
        return {
            "provider": self.provider,
            "breakers": {k: b.state for k, b in self.breakers.items()},
            "usage": self.usage.summary(),
            "primary": self.primary.health(),
            "fallback": self.secondary.health(),
        }
