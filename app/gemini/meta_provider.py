"""Meta Model API adapter. Uses the shared bounded HTTP transport, LLM only.

Protocol: https://dev.meta.ai/docs/protocols/chat-completions
Structured JSON: https://dev.meta.ai/docs/structured-output
"""
from app.gemini.openai_provider import OpenAICompatProvider
from app.gemini.pool import GeminiError


class MetaModelProvider(OpenAICompatProvider):
    @property
    def provider(self) -> str:
        return "meta"

    @property
    def _keys(self) -> list[str]:
        return self.s.meta_keys

    @property
    def _base_url(self) -> str:
        return self.s.meta_base_url

    @property
    def _llm_model(self) -> str:
        return self.s.meta_llm_model

    def _chat_payload(self, model, messages, schema, temperature, max_output_tokens) -> dict:
        return {"model": model, "messages": messages, "temperature": temperature,
                "max_completion_tokens": max_output_tokens,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "search_result", "schema": schema}}}

    async def embed(self, *args, **kwargs):
        raise GeminiError("invalid_input", "Meta Model API chỉ dùng cho LLM; không thay thế embedding")
