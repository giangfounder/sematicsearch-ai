import asyncio
import json
import time

import httpx
import numpy as np
import pytest

from app import repo
from app.db import create_pool, migrate
from app.gemini.fake import FakeGemini
from app.gemini.fallback import FallbackGemini
from app.gemini.openai_provider import OpenAICompatProvider
from app.gemini.pool import GeminiError
from app.ingest.vectors import embed_demo
from tests.conftest import make_settings


def settings(**kw):
    return make_settings('', openai_api_key='synthetic-test-key', **kw)


@pytest.mark.parametrize('output', ['[]', 'null', '{"intent":42}', '{"intent":"bad"}', '{"intent":NaN}'])
async def test_rejects_schema_violations(output):
    schema={'type':'object','properties':{'intent':{'type':'string','enum':['valid']}},'required':['intent']}
    def handler(request):
        body=json.loads(request.content)
        assert 'JSON Schema' in body['messages'][0]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':output}}]})
    provider=OpenAICompatProvider(settings(),transport=httpx.MockTransport(handler))
    await provider.start()
    try:
        with pytest.raises(GeminiError) as error:
            await provider.generate_json(system='s',contents='c',schema=schema,call_type='understand',timeout_ms=1000)
        assert error.value.reason=='bad_output'
    finally:await provider.close()


async def test_billing_cooldown_is_not_a_rate_limit_or_repeated_request():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,json={'error':{'code':'insufficient_quota','type':'insufficient_quota'}})
    provider=OpenAICompatProvider(settings(),transport=httpx.MockTransport(handler))
    await provider.start()
    try:
        for _ in range(2):
            with pytest.raises(GeminiError) as error:
                await provider.embed(['synthetic'],'RETRIEVAL_DOCUMENT',call_type='embed_doc',timeout_ms=1000)
            assert error.value.reason=='quota_exhausted'
        assert len(calls)==1
        assert provider.health()['available_keys']==0
    finally:await provider.close()


async def test_provider_errors_do_not_echo_input_or_credential():
    raw='private-customer-input synthetic-secret-value'
    provider=OpenAICompatProvider(settings(),transport=httpx.MockTransport(lambda _:httpx.Response(400,json={'error':{'message':raw}})))
    await provider.start()
    try:
        with pytest.raises(GeminiError) as error:
            await provider.generate_json(system='s',contents='c',schema={},call_type='understand',timeout_ms=1000)
        assert raw not in str(error.value)
    finally:await provider.close()


async def test_duplicate_embedding_indices_are_rejected():
    provider=OpenAICompatProvider(settings(embed_dim=2),transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'data':[{'index':0,'embedding':[1,2]},{'index':0,'embedding':[2,3]}]})))
    await provider.start()
    try:
        with pytest.raises(GeminiError) as error:
            await provider.embed(['a','b'],'RETRIEVAL_DOCUMENT',call_type='embed_doc',timeout_ms=1000)
        assert error.value.reason=='bad_output'
    finally:await provider.close()


async def test_semaphore_wait_is_inside_request_deadline():
    provider=OpenAICompatProvider(settings(gemini_max_concurrency=1),transport=httpx.MockTransport(lambda _:httpx.Response(200,json={})))
    await provider.start();await provider.sem.acquire()
    start=time.monotonic()
    try:
        with pytest.raises(GeminiError) as error:
            await provider.generate_json(system='s',contents='c',schema={},call_type='understand',timeout_ms=30)
        assert error.value.reason=='timeout'
        assert time.monotonic()-start<.5
    finally:provider.sem.release();await provider.close()


async def test_staging_keeps_old_space_until_atomic_activation(db_url):
    pool=await create_pool(db_url);s=make_settings(db_url,embed_dim=64)
    old_model='gemini-embedding-001';new_model='text-embedding-3-small';gem=FakeGemini(s)
    try:
        await migrate(pool)
        demo=await repo.create_demo(pool,{'slug':'staged','name':'Staged','embed_model':old_model,'embed_dim':64})
        await repo.upsert_products(pool,demo['id'],[{'sku':'one','name':'Synthetic product'}],mode='replace')
        old=await embed_demo(pool,gem,demo['id'],per_minute=10000,timeout_ms=1000)
        gem.fail['embed_doc']='quota_exhausted'
        with pytest.raises(GeminiError):
            await embed_demo(pool,gem,demo['id'],per_minute=10000,timeout_ms=1000,target_model=new_model)
        current=await repo.get_demo_by_id(pool,demo['id'])
        assert current['embed_model']==old_model
        assert (await repo.list_vectors(pool,demo['id']))
        gem.fail.clear()
        staged=await embed_demo(pool,gem,demo['id'],per_minute=10000,timeout_ms=1000,target_model=new_model)
        assert (await repo.get_demo_by_id(pool,demo['id']))['embed_model']==old_model
        assert not await repo.set_demo_embed_model(pool,demo['id'],new_model,64,expected_version=staged['data_version']-1)
        assert await repo.set_demo_embed_model(pool,demo['id'],new_model,64,expected_version=staged['data_version'])
        vectors=await repo.list_vectors(pool,demo['id'])
        assert {v['embed_model'] for v in vectors}=={old_model,new_model}
        from app.catalog.index import load_index
        index=await load_index(pool,'staged')
        assert index.embed_model==new_model and index.n_vectors==staged['total_vectors']
    finally:await pool.close()


async def test_complete_job_failure_does_not_switch_active_model(db_url,monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    s=make_settings(db_url,openai_api_key='synthetic',embed_dim=64,gemini_embed_model='gemini-embedding-001')
    primary,secondary=FakeGemini(s),FakeGemini(s)
    primary.fail['embed_doc']='quota_exhausted';secondary.fail['embed_doc']='quota_exhausted'
    monkeypatch.setattr(main,'make_gemini',lambda _:FallbackGemini(primary,secondary))
    with TestClient(main.create_app(s)) as c:
        c.post('/v1/admin/demos',json={'slug':'failed','name':'Failed','embed_dim':64})
        c.post('/v1/admin/demos/failed/products?reembed=false',json=[{'sku':'one','name':'Synthetic product'}])
        job=c.post('/v1/admin/demos/failed/embed').json()['job_id']
        for _ in range(200):
            result=c.get('/v1/admin/jobs/'+job).json()
            if result['status'] in ('done','error'):break
            await asyncio.sleep(.02)
        assert result['status']=='error'
        assert c.get('/v1/admin/demos/failed').json()['embed_model']=='gemini-embedding-001'
