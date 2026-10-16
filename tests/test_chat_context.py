import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings, seed_demo


def test_chat_context_is_local_bounded_and_does_not_expose_raw_columns(client, monkeypatch):
    seed_demo(client)
    gem = client.app.state.gemini
    embed, llm = AsyncMock(side_effect=AssertionError('Unexpected paid embedding')), AsyncMock(side_effect=AssertionError('Unexpected LLM'))
    monkeypatch.setattr(gem, 'embed', embed)
    monkeypatch.setattr(gem, 'generate_json', llm)
    response = client.post('/v1/tables/dm/chat-context', json={'text': 'Tủ lạnh Samsung', 'top_k': 5})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['external_ai_calls'] == 0 and result['retrieval'] == 'lexical'
    assert 1 <= len(result['rows']) <= 3
    assert len(json.dumps(result['rows'], ensure_ascii=False)) <= 3000
    assert all('raw' not in row and 'data' not in row for row in result['rows'])
    embed.assert_not_awaited()
    llm.assert_not_awaited()
    assert response.headers['cache-control'] == 'no-store'


def test_chat_context_requires_session_and_respects_table_ownership(db_url):
    app = create_app(make_settings(db_url, seed_account_email='owner@example.test', seed_account_password='synthetic-password'))
    with TestClient(app) as c:
        headers = {'Authorization': 'Bearer ' + c.post('/v1/auth/login', json={
            'email': 'owner@example.test', 'password': 'synthetic-password'}).json()['token']}
        assert c.post('/v1/admin/demos', headers=headers, json={'slug': 'private', 'name': 'Private', 'embed_dim': 64}).status_code == 201
        assert c.post('/v1/tables/private/chat-context', json={'text': 'Question'}).status_code == 401
        c.portal.call(app.state.accounts.ensure_account, 'other@example.test', 'synthetic-password')
        other = {'Authorization': 'Bearer ' + c.post('/v1/auth/login', json={
            'email': 'other@example.test', 'password': 'synthetic-password'}).json()['token']}
        assert c.post('/v1/tables/private/chat-context', headers=other, json={'text': 'Question'}).status_code == 404
