"""OpenRouter provider: LLM-only, tự xoay model :free khi hết quota/rate limit/lỗi."""
import json

import httpx
import pytest

from app.gemini.fallback import FallbackGemini
from app.gemini.openrouter_provider import OpenRouterProvider
from app.gemini.pool import GeminiError, make_gemini, redact
from tests.conftest import make_settings

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
CALL = dict(system="Return JSON", contents="Synthetic probe", schema=SCHEMA,
            call_type="understand", timeout_ms=1000)

# Dựng từ mảnh để không tạo literal khớp mẫu khoá thật (secret scanner của GitHub).
KEY = "sk-" + "or-" + "v1-" + "synthetic" + "0" * 24
MODELS = "vendor/bad-model:free,vendor/good-model:free"


def settings(**kwargs):
    return make_settings("", openrouter_api_key=KEY, openrouter_models=MODELS, **kwargs)


def completion(content='{"ok":true}', reason="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": reason}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5}}


def test_factory_order_and_key_hidden():
    assert make_gemini(settings()).provider == "fake+openrouter"
    assert make_gemini(settings(openrouter_fallback=False)).provider == "fake"
    assert KEY not in repr(settings())
    assert redact(f"key={KEY}") == "key=***"


async def test_protocol_payload_and_schema_validation():
    seen = []

    def handle(request):
        seen.append(json.loads(request.content)["model"])
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"].startswith("Bearer sk-or-")
        return httpx.Response(200, json=completion())

    p = OpenRouterProvider(settings(), transport=httpx.MockTransport(handle))
    await p.start()
    try:
        assert await p.generate_json(**CALL) == {"ok": True}
        assert seen == ["vendor/bad-model:free"]
        assert p.usage.summary()["understand"]["input_tokens"] == 3
    finally:
        await p.close()


async def test_rotates_to_next_model_on_rate_limit():
    seen = []

    def handle(request):
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "vendor/bad-model:free":
            return httpx.Response(429, json={"error": {"code": 429, "message": "rate limited"}})
        return httpx.Response(200, json=completion())

    p = OpenRouterProvider(settings(), transport=httpx.MockTransport(handle))
    await p.start()
    try:
        assert await p.generate_json(**CALL) == {"ok": True}
        assert seen == ["vendor/bad-model:free", "vendor/good-model:free"]
        assert p.health()["current_model"] == "vendor/good-model:free"
    finally:
        await p.close()


async def test_rotates_on_bad_output_then_all_fail_raises():
    def handle(request):
        model = json.loads(request.content)["model"]
        if model == "vendor/bad-model:free":
            return httpx.Response(200, json=completion('{"ok":"wrong type"}'))
        return httpx.Response(200, json=completion('[]'))

    p = OpenRouterProvider(settings(), transport=httpx.MockTransport(handle))
    await p.start()
    try:
        with pytest.raises(GeminiError) as error:
            await p.generate_json(**CALL)
        assert error.value.reason == "bad_output"
    finally:
        await p.close()


async def test_does_not_rotate_on_authentication_error():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"code": 401}})

    p = OpenRouterProvider(settings(), transport=httpx.MockTransport(handle))
    await p.start()
    try:
        with pytest.raises(GeminiError) as error:
            await p.generate_json(**CALL)
        assert error.value.reason == "authentication_error"
        assert len(calls) == 1
    finally:
        await p.close()


async def test_embed_is_rejected_and_not_routed_by_fallback():
    s = settings()
    from app.gemini.fake import FakeGemini

    primary = FakeGemini(s)
    p = OpenRouterProvider(s, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    chain = FallbackGemini(primary, p)
    with pytest.raises(GeminiError, match="invalid_input"):
        await chain.embed(["x"], "RETRIEVAL_QUERY", call_type="embed_query", timeout_ms=100,
                          model="text-embedding-3-small", dim=64)
