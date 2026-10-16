"""Provider OpenRouter (OpenAI-compatible) làm LLM dự phòng.

Đặc điểm riêng: OpenRouter giới hạn theo TỪNG model (`:free` có quota/ngày riêng),
nên khi một model hết quota / bị rate limit / trả JSON hỏng, adapter tự chuyển sang
model kế tiếp trong `OPENROUTER_MODELS` thay vì bỏ cuộc. Chỉ dùng cho LLM; KHÔNG dùng
cho embedding (không trộn không gian vector). Key không bao giờ lộ ra log/exception.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.config import Settings
from app.gemini.openai_provider import TRANSIENT_REASONS, OpenAICompatProvider
from app.gemini.pool import GeminiError

log = logging.getLogger("openrouter")

# Lý do cho phép xoay sang model kế tiếp: hết quota/rate limit + model trả output hỏng
# hoặc không hỗ trợ response_format (một model khác có thể hỗ trợ).
_ROTATE = TRANSIENT_REASONS | {"bad_output", "unsupported_format"}


class OpenRouterProvider(OpenAICompatProvider):
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(settings, transport=transport)
        self._model_idx = 0

    @property
    def provider(self) -> str:
        return "openrouter"

    @property
    def _keys(self) -> list[str]:
        return self.s.openrouter_keys

    @property
    def _base_url(self) -> str:
        return self.s.openrouter_base_url

    @property
    def _llm_model(self) -> str:
        models = self.s.openrouter_model_list
        return models[self._model_idx % len(models)] if models else ""

    async def generate_json(self, *, system, contents, schema, call_type, timeout_ms, demo_id=0,
                            model=None, max_output_tokens=1024, temperature=0.0) -> dict:
        models = self.s.openrouter_model_list
        if not models:
            raise GeminiError("unavailable", "openrouter: chưa cấu hình model")
        deadline = time.monotonic() + timeout_ms / 1000
        last: GeminiError | None = None
        start = self._model_idx % len(models)
        for step in range(len(models)):
            idx = (start + step) % len(models)
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining < 1:
                break
            # 429 ở OpenRouter tính theo model (không phải theo key): bỏ cooldown key
            # để model kế tiếp vẫn dùng được cùng key.
            self.cooldown = [0.0] * len(self.cooldown)
            self.cooldown_reason = [""] * len(self.cooldown_reason)
            try:
                out = await super().generate_json(
                    system=system, contents=contents, schema=schema, call_type=call_type,
                    timeout_ms=remaining, demo_id=demo_id, model=models[idx],
                    max_output_tokens=max_output_tokens, temperature=temperature)
                self._model_idx = idx
                return out
            except GeminiError as exc:
                last = exc
                if exc.reason not in _ROTATE:
                    raise
                log.info("openrouter %s: %s -> thử model kế tiếp", exc.reason, models[idx])
        raise last or GeminiError("rate_limited", "openrouter: hết model khả dụng")

    async def embed(self, *args, **kwargs):
        raise GeminiError("invalid_input", "OpenRouter chỉ dùng cho LLM, không thay thế embedding")

    def health(self) -> dict:
        return {**super().health(), "models": self.s.openrouter_model_list,
                "current_model": self._llm_model}
