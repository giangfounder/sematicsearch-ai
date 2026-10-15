"""Fallback Gemini -> GPT: điều hướng embed theo model, chuyển LLM khi hết quota,
provider OpenAI-compatible, và tự đổi model bảng khi ingest."""
from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from app import repo
from app.db import create_pool, migrate
from app.gemini.fake import FakeGemini
from app.gemini.fallback import FallbackGemini
from app.gemini.openai_provider import OpenAICompatProvider
from app.gemini.pool import GeminiError, make_gemini
from tests.conftest import make_settings

GPT_EMBED = "text-embedding-3-small"
GEMINI_EMBED = "gemini-embedding-001"


def gpt_settings(**kw):
    base = dict(openai_api_key="sk-test", openai_embed_model=GPT_EMBED,
                openai_llm_model="gpt-4o-mini", gemini_embed_model=GEMINI_EMBED)
    base.update(kw)
    return make_settings("", **base)


class RecordingFake(FakeGemini):
    def __init__(self, settings):
        super().__init__(settings)
        self.embed_models: list = []
        self.llm_models: list = []

    async def embed(self, texts, task, **kw):
        self.embed_models.append(kw.get("model"))
        return await super().embed(texts, task, **kw)

    async def generate_json(self, **kw):
        self.llm_models.append(kw.get("model"))
        return await super().generate_json(**kw)


# ------------------------------------------------------------------ make_gemini
def test_make_gemini_wraps_only_when_key_present():
    assert isinstance(make_gemini(gpt_settings()), FallbackGemini)
    assert make_gemini(gpt_settings()).provider == "fake+gpt"
    plain = make_gemini(make_settings(""))
    assert not isinstance(plain, FallbackGemini)
    assert plain.provider == "fake"
    off = make_gemini(gpt_settings(gpt_fallback=False))
    assert not isinstance(off, FallbackGemini)


# ------------------------------------------------------------------ wrapper
async def test_embed_routes_by_model_and_shares_usage():
    s = gpt_settings(embed_dim=64)
    primary, secondary = RecordingFake(s), RecordingFake(s)
    gem = FallbackGemini(primary, secondary)
    assert gem.usage is primary.usage and secondary.usage is primary.usage

    await gem.embed(["a"], "RETRIEVAL_QUERY", call_type="embed_query", timeout_ms=100,
                    model=GEMINI_EMBED, dim=64)
    assert primary.embed_models == [GEMINI_EMBED] and secondary.embed_models == []

    await gem.embed(["b"], "RETRIEVAL_DOCUMENT", call_type="embed_doc", timeout_ms=100,
                    model=GPT_EMBED, dim=64)
    assert secondary.embed_models == [GPT_EMBED]


async def test_llm_falls_back_on_transient_reason():
    s = gpt_settings()
    primary, secondary = RecordingFake(s), RecordingFake(s)
    primary.fail["understand"] = "rate_limited"
    secondary.handlers["understand"] = lambda **_kw: {"intent": "find_product"}
    gem = FallbackGemini(primary, secondary)

    out = await gem.generate_json(system="s", contents="c", schema={}, call_type="understand",
                                  timeout_ms=100, model="gemini-3.5-flash-lite")
    assert out == {"intent": "find_product"}
    # model Gemini không được chuyển nguyên sang GPT (để provider tự chọn model của nó)
    assert secondary.llm_models == [None]
    assert gem.usage.summary()["understand"]["calls"] == 1


async def test_llm_does_not_fall_back_on_invalid_input():
    s = gpt_settings()
    primary, secondary = RecordingFake(s), RecordingFake(s)
    primary.fail["understand"] = "invalid_input"
    gem = FallbackGemini(primary, secondary)
    with pytest.raises(GeminiError):
        await gem.generate_json(system="s", contents="c", schema={}, call_type="understand",
                                timeout_ms=100)
    assert secondary.llm_models == []


# ------------------------------------------------------------------ OpenAI provider
def _embed_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    n = len(body["input"])
    data = [{"object": "embedding", "index": i, "embedding": [0.01 * (i + 1)] * 64} for i in range(n)]
    return httpx.Response(200, json={"data": data, "model": body["model"], "usage": {}})


async def test_openai_provider_embed_shape_and_usage():
    s = gpt_settings(embed_dim=64)
    p = OpenAICompatProvider(s, transport=httpx.MockTransport(_embed_handler))
    await p.start()
    try:
        v = await p.embed(["a", "b"], "RETRIEVAL_DOCUMENT", call_type="embed_doc",
                          timeout_ms=2000, model=None, dim=64)
        assert v.shape == (2, 64)
        assert np.allclose(np.linalg.norm(v, axis=1), 1.0)
        assert p.usage.summary()["embed_doc"]["calls"] == 1
    finally:
        await p.close()


async def test_openai_provider_rotates_keys_on_429():
    s = gpt_settings(openai_api_key="sk-a,sk-b", embed_dim=64)
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(429, text='{"error":"rate limited"}')

    p = OpenAICompatProvider(s, transport=httpx.MockTransport(handler))
    await p.start()
    try:
        with pytest.raises(GeminiError) as ei:
            await p.embed(["a"], "RETRIEVAL_DOCUMENT", call_type="embed_doc", timeout_ms=2000, dim=64)
        assert ei.value.reason in ("rate_limited", "quota_exhausted")
        assert len(set(seen)) == 2  # cả 2 key đều đã được dùng
    finally:
        await p.close()


async def test_openai_provider_generate_json():
    s = gpt_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"intent": "x"}\n```'}}],
                                         "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    p = OpenAICompatProvider(s, transport=httpx.MockTransport(handler))
    await p.start()
    try:
        out = await p.generate_json(system="s", contents="c", schema={}, call_type="understand", timeout_ms=2000)
        assert out == {"intent": "x"}
        summary = p.usage.summary()["understand"]
        assert summary["input_tokens"] == 7 and summary["output_tokens"] == 3
    finally:
        await p.close()


# ------------------------------------------------------------------ repo helper
async def test_set_demo_embed_model(db_url):
    pool = await create_pool(db_url)
    try:
        await migrate(pool)
        demo = await repo.create_demo(pool, {"slug": "gpt-demo", "name": "G",
                                             "embed_model": GEMINI_EMBED, "embed_dim": 768})
        assert await repo.set_demo_embed_model(pool, demo["id"], GPT_EMBED, 768) is True
        got = await repo.get_demo_by_id(pool, demo["id"])
        assert got["embed_model"] == GPT_EMBED and got["embed_dim"] == 768
        assert await repo.set_demo_embed_model(pool, demo["id"], GPT_EMBED, 768) is False
    finally:
        await pool.close()


# ------------------------------------------------------------------ end to end
async def test_ingest_switches_demo_to_gpt_when_gemini_exhausted(db_url, monkeypatch):
    import app.main as main_mod
    from app.main import create_app
    from tests.conftest import DEFS, PRODUCTS, wait_job

    s = make_settings(db_url, openai_api_key="sk-test", openai_embed_model=GPT_EMBED,
                      gemini_embed_model=GEMINI_EMBED, embed_dim=64)

    class Exhausted(FakeGemini):
        """Gemini 'hết quota' cho mọi model khác GPT; model GPT thì thành công."""

        async def embed(self, texts, task, **kw):
            if kw.get("model") != GPT_EMBED:
                raise GeminiError("rate_limited", "gemini hết quota")
            return await super().embed(texts, task, **kw)

    monkeypatch.setattr(main_mod, "make_gemini",
                        lambda settings: FallbackGemini(Exhausted(settings), FakeGemini(settings)))

    from fastapi.testclient import TestClient

    with TestClient(create_app(s)) as c:
        assert c.post("/v1/admin/demos", json={"slug": "sw", "name": "SW", "embed_dim": 64}).status_code == 201
        assert c.put("/v1/admin/demos/sw/definitions?reembed=false", json=DEFS).status_code == 200
        assert c.post("/v1/admin/demos/sw/products?reembed=false", json=PRODUCTS).status_code == 200
        job = c.post("/v1/admin/demos/sw/embed").json()["job_id"]
        wait_job(c, job)

    pool = await create_pool(db_url)
    try:
        demo = await repo.get_demo(pool, "sw")
        assert demo["embed_model"] == GPT_EMBED
        assert demo["embed_dim"] == 64
    finally:
        await pool.close()
