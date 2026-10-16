"""Third-provider behavior and Meta Model API wire protocol; no external API calls."""
import asyncio
import json
import time

import httpx
import pytest

from app.gemini.fallback import FallbackGemini
from app.gemini.meta_provider import MetaModelProvider
from app.gemini.pool import GeminiError, make_gemini, redact
from tests.conftest import make_settings
from tests.test_fallback import RecordingFake, GEMINI_EMBED, GPT_EMBED

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
CALL = dict(system="Return JSON", contents="Synthetic probe", schema=SCHEMA,
            call_type="understand", timeout_ms=1000)


def settings(**kwargs):
    return make_settings("", meta_api_key="LLM_0000000000000000_synthetic_test_key", **kwargs)


def completion(content='{"ok":true}', reason="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": reason}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5}}


def test_factory_order_and_meta_without_gpt():
    assert make_gemini(settings(openai_api_key="synthetic")).provider == "fake+gpt+meta"
    assert make_gemini(settings()).provider == "fake+meta"
    assert make_gemini(settings(meta_fallback=False)).provider == "fake"
    assert "synthetic_test_key" not in repr(settings())
    assert redact("key=LLM_0000000000000000_synthetic_test_key") == "key=***"
    assert redact("key=LLM|0000000000000000|synthetic_test_key") == "key=***"


async def test_meta_protocol_and_schema_validation():
    def handle(request):
        assert str(request.url) == "https://api.meta.ai/v1/chat/completions"
        assert request.headers["authorization"].startswith("Bearer LLM_")
        payload = json.loads(request.content)
        assert payload["model"] == "muse-spark-1.3"
        assert payload["max_completion_tokens"] == 128 and "max_tokens" not in payload
        assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
        return httpx.Response(200, json=completion())
    p = MetaModelProvider(settings(), transport=httpx.MockTransport(handle))
    await p.start()
    try:
        assert await p.generate_json(**CALL, max_output_tokens=128) == {"ok": True}
        assert p.usage.summary()["understand"]["input_tokens"] == 3
    finally:
        await p.close()


@pytest.mark.parametrize("body", [completion('{"ok":"wrong type"}'), completion('[]'),
                                 completion('{"ok":true}', "length"),
                                 {"completion_message": {"content": '{"ok":true}'}},
                                 completion('{"ok":NaN}')])
async def test_meta_rejects_invalid_outputs(body):
    p = MetaModelProvider(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    await p.start()
    try:
        with pytest.raises(GeminiError, match="bad_output"):
            await p.generate_json(**CALL)
    finally:
        await p.close()


async def test_meta_billing_cools_key_without_repeated_calls_or_secret_echo():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(402, json={"error": {"type": "billing_error", "code": "billing_not_configured",
                                                  "message": "private provider response"}})
    p = MetaModelProvider(settings(), transport=httpx.MockTransport(handle))
    await p.start()
    try:
        for _ in range(2):
            with pytest.raises(GeminiError) as error:
                await p.generate_json(**CALL)
            assert error.value.reason == "quota_exhausted"
            assert "private" not in str(error.value)
        assert len(calls) == 1
        assert p.health()["available_keys"] == 0
        assert p.health()["cooldown_reasons"] == ["quota_exhausted"]
    finally:
        await p.close()


@pytest.mark.parametrize("gpt_reason", ["quota_exhausted", "authentication_error", "bad_output"])
async def test_chain_gemini_gpt_meta_and_embedding_isolation(gpt_reason):
    s = settings(openai_api_key="synthetic")
    primary, secondary, tertiary = [RecordingFake(s) for _ in range(3)]
    primary.fail["understand"] = "quota_exhausted"
    secondary.fail["understand"] = gpt_reason
    tertiary.handlers["understand"] = lambda **_: {"ok": True}
    p = FallbackGemini(primary, secondary, tertiary)
    assert await p.generate_json(**CALL, model="gemini-model") == {"ok": True}
    assert primary.llm_models == ["gemini-model"]
    assert secondary.llm_models == [None] and tertiary.llm_models == [None]
    assert tertiary.usage is primary.usage
    for model in (GEMINI_EMBED, GPT_EMBED):
        await p.embed(["synthetic"], "RETRIEVAL_QUERY", call_type="embed_query", timeout_ms=100, model=model, dim=64)
    assert tertiary.embed_models == []


async def test_deadline_and_cancellation_stop_chain():
    s = settings()
    primary, tertiary = RecordingFake(s), RecordingFake(s)
    async def slow(**kwargs):
        await asyncio.sleep(1)
    primary.generate_json = slow
    p = FallbackGemini(primary, None, tertiary)
    started = time.monotonic()
    with pytest.raises(GeminiError, match="timeout"):
        await p.generate_json(**{**CALL, "timeout_ms": 30})
    assert time.monotonic() - started < .5
    assert tertiary.llm_models == []
    task = asyncio.create_task(p.generate_json(**CALL))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert tertiary.llm_models == []


async def test_meta_only_does_not_receive_embeddings():
    s = settings()
    primary, tertiary = RecordingFake(s), RecordingFake(s)
    p = FallbackGemini(primary, None, tertiary)
    with pytest.raises(GeminiError, match="unavailable"):
        await p.embed(["synthetic"], "RETRIEVAL_QUERY", call_type="embed_query", timeout_ms=100,
                      model=GPT_EMBED, dim=64)
    assert tertiary.embed_models == []
    with pytest.raises(GeminiError, match="invalid_input"):
        await MetaModelProvider(s).embed([])
