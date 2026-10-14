"""Credential reveal: encryption at rest, response hygiene, and owner isolation.

All credentials are generated inside isolated test databases. Assertion messages
deliberately avoid printing the raw keys or their encrypted copies.
"""
from __future__ import annotations

import hmac

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.keys import hash_key
from app.main import create_app
from tests.conftest import make_settings


ADMIN = {"X-Admin-Key": "test-reveal-admin"}


def _settings(db_url, encryption_key="", **kwargs):
    return make_settings(
        db_url,
        admin_keys=ADMIN["X-Admin-Key"],
        table_key_encryption_key=encryption_key,
        **kwargs,
    )


def _table(client, slug="reveal", headers=None):
    response = client.post(
        "/v1/admin/demos",
        json={"slug": slug, "name": "Reveal test", "embed_dim": 64},
        headers=ADMIN if headers is None else headers,
    )
    assert response.status_code == 201, "test table creation failed"
    return response.json()


def _key(client, slug="reveal", headers=None, scopes=None):
    response = client.post(
        f"/v1/tables/{slug}/keys",
        json={"name": "Test key", "scopes": scopes or ["read"]},
        headers=ADMIN if headers is None else headers,
    )
    assert response.status_code == 201, "test key creation failed"
    return response.json()


def _reveal(client, key_id, slug="reveal", headers=None):
    return client.post(
        f"/v1/tables/{slug}/keys/{key_id}/reveal",
        headers=ADMIN if headers is None else headers,
    )


def _assert_same_secret(actual, expected):
    assert hmac.compare_digest(actual, expected), "revealed credential differs"


def _assert_no_secrets(text, *secrets):
    assert not any(value and value in text for value in secrets), "credential leaked"


def _record(client, key_id):
    return client.portal.call(
        client.app.state.pool.fetchrow,
        "SELECT key_hash, key_encrypted FROM table_keys WHERE id=$1",
        key_id,
    )


def test_key_encrypted_at_rest_and_not_in_listing_or_auth_cache(db_url):
    cipher = Fernet.generate_key()
    with TestClient(create_app(_settings(db_url, cipher.decode()))) as client:
        _table(client)
        created = _key(client)
        assert created["can_reveal"] is True
        row = _record(client, created["id"])
        encrypted = row["key_encrypted"]
        assert isinstance(encrypted, bytes) and encrypted, "ciphertext was not stored"
        assert not hmac.compare_digest(encrypted, created["key"].encode()), "key stored in plaintext"
        _assert_same_secret(Fernet(cipher).decrypt(encrypted).decode(), created["key"])
        _assert_same_secret(row["key_hash"], hash_key(created["key"]))

        listing = client.get("/v1/tables/reveal/keys", headers=ADMIN)
        assert listing.status_code == 200
        metadata = listing.json()[0]
        assert metadata["id"] == created["id"] and metadata["can_reveal"] is True
        assert not {"key", "key_hash", "key_encrypted"}.intersection(metadata)
        _assert_no_secrets(listing.text, created["key"], encrypted.decode())

        cache = client.app.state.keys.by_hash
        assert cache, "auth cache was not refreshed"
        assert all("key_encrypted" not in value and "key" not in value for value in cache.values())
        _assert_no_secrets(repr(cache), created["key"], encrypted.decode())


def test_reveal_returns_key_only_on_post_and_prevents_response_caching(db_url, caplog):
    with TestClient(create_app(_settings(db_url, Fernet.generate_key().decode()))) as client:
        _table(client)
        created = _key(client)
        revealed = _reveal(client, created["id"])
        assert revealed.status_code == 200
        assert set(revealed.json()) == {"id", "key"}
        assert revealed.json()["id"] == created["id"]
        _assert_same_secret(revealed.json()["key"], created["key"])
        assert "no-store" in revealed.headers.get("cache-control", "")
        assert revealed.headers.get("pragma") == "no-cache"
        assert client.get(f"/v1/tables/reveal/keys/{created['id']}/reveal", headers=ADMIN).status_code == 405
        _assert_no_secrets(caplog.text, created["key"])


def test_reveal_survives_application_restart_with_same_encryption_key(db_url):
    settings = _settings(db_url, Fernet.generate_key().decode())
    with TestClient(create_app(settings)) as client:
        _table(client)
        created = _key(client)
    with TestClient(create_app(settings)) as reopened:
        response = _reveal(reopened, created["id"])
        assert response.status_code == 200
        _assert_same_secret(response.json()["key"], created["key"])


def test_legacy_hash_only_key_keeps_creation_and_auth_without_reveal(db_url):
    with TestClient(create_app(_settings(db_url))) as client:
        _table(client)
        created = _key(client)
        assert created["key"].startswith("sk_tbl_")
        assert created["can_reveal"] is False
        assert _record(client, created["id"])["key_encrypted"] is None
        assert client.app.state.keys.check(created["key"], "reveal", "read") is True

    # Enabling encryption cannot recover credentials whose original value was discarded.
    with TestClient(create_app(_settings(db_url, Fernet.generate_key().decode()))) as reopened:
        listing = reopened.get("/v1/tables/reveal/keys", headers=ADMIN)
        assert listing.status_code == 200 and listing.json()[0]["can_reveal"] is False
        response = _reveal(reopened, created["id"])
        assert response.status_code == 409
        _assert_no_secrets(response.text, created["key"])


def test_reveal_missing_or_wrong_table_key_is_not_found(db_url):
    with TestClient(create_app(_settings(db_url, Fernet.generate_key().decode()))) as client:
        _table(client)
        _table(client, "other")
        created = _key(client)
        assert _reveal(client, created["id"] + 99999).status_code == 404
        assert _reveal(client, created["id"], slug="other").status_code == 404
        assert _reveal(client, created["id"], slug="missing").status_code == 404
        assert client.delete(f"/v1/tables/reveal/keys/{created['id']}", headers=ADMIN).status_code == 200
        assert _reveal(client, created["id"]).status_code == 404


def test_public_and_table_keys_cannot_reveal_credentials(db_url):
    with TestClient(create_app(_settings(db_url, Fernet.generate_key().decode(), api_keys="test-public"))) as client:
        _table(client)
        read_key = _key(client)
        write_key = _key(client, scopes=["read", "write"])
        headers_to_reject = [
            {},
            {"X-API-Key": "test-public"},
            {"X-API-Key": read_key["key"]},
            {"X-API-Key": write_key["key"]},
            {"X-Table-Key": write_key["key"]},
            {"Authorization": "Bearer invalid-session"},
        ]
        for headers in headers_to_reject:
            response = _reveal(client, read_key["id"], headers=headers)
            assert response.status_code == 401
            _assert_no_secrets(response.text, read_key["key"], write_key["key"])


def _login(client, email):
    response = client.post("/v1/auth/login", json={"email": email, "password": "test-password"})
    assert response.status_code == 200, "test account login failed"
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_owner_can_reveal_while_other_account_cannot_discover_key(db_url):
    with TestClient(create_app(_settings(db_url, Fernet.generate_key().decode()))) as client:
        for email in ("owner@example.test", "other@example.test"):
            response = client.post(
                "/v1/admin/accounts",
                json={"email": email, "password": "test-password", "name": "Test account"},
                headers=ADMIN,
            )
            assert response.status_code == 201, "test account creation failed"
            assert response.json()["is_admin"] is False

        owner = _login(client, "owner@example.test")
        other = _login(client, "other@example.test")
        _table(client, headers=owner)
        created = _key(client, headers=owner)
        response = _reveal(client, created["id"], headers=owner)
        assert response.status_code == 200
        _assert_same_secret(response.json()["key"], created["key"])

        forbidden = _reveal(client, created["id"], headers=other)
        missing = _reveal(client, created["id"], slug="missing", headers=other)
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json() or "key" not in forbidden.json()
        assert client.get("/v1/tables/reveal/keys", headers=other).status_code == 404
        _assert_no_secrets(forbidden.text, created["key"])
        assert _reveal(client, created["id"], headers=ADMIN).status_code == 200


@pytest.mark.parametrize("damage", ["invalid-token", "swapped-ciphertext"])
def test_reveal_rejects_tampered_or_swapped_ciphertext_without_leaks(db_url, caplog, damage):
    with TestClient(create_app(_settings(db_url, Fernet.generate_key().decode()))) as client:
        _table(client)
        first = _key(client)
        second = _key(client)
        replacement = b"invalid-encrypted-credential"
        if damage == "swapped-ciphertext":
            replacement = _record(client, second["id"])["key_encrypted"]
        client.portal.call(
            client.app.state.pool.execute,
            "UPDATE table_keys SET key_encrypted=$2 WHERE id=$1",
            first["id"], replacement,
        )
        response = _reveal(client, first["id"])
        assert response.status_code == 503
        _assert_no_secrets(response.text, first["key"], second["key"], replacement.decode())
        _assert_no_secrets(caplog.text, first["key"], second["key"], replacement.decode())
        # A corrupt saved copy must not change the independent hash-based auth path.
        assert client.app.state.keys.check(first["key"], "reveal", "read") is True


@pytest.mark.parametrize("configuration", ["missing", "wrong"])
def test_reveal_reports_unavailable_encryption_after_restart_without_leaks(db_url, caplog, configuration):
    original_cipher = Fernet.generate_key().decode()
    with TestClient(create_app(_settings(db_url, original_cipher))) as client:
        _table(client)
        created = _key(client)
        encrypted = _record(client, created["id"])["key_encrypted"].decode()

    current_cipher = "" if configuration == "missing" else Fernet.generate_key().decode()
    with TestClient(create_app(_settings(db_url, current_cipher))) as reopened:
        response = _reveal(reopened, created["id"])
        assert response.status_code == (409 if configuration == "missing" else 503)
        _assert_no_secrets(response.text, created["key"], encrypted, original_cipher, current_cipher)
        _assert_no_secrets(caplog.text, created["key"], encrypted, original_cipher, current_cipher)
        assert reopened.app.state.keys.check(created["key"], "reveal", "read") is True
        listing = reopened.get("/v1/tables/reveal/keys", headers=ADMIN)
        assert listing.status_code == 200
        _assert_no_secrets(listing.text, created["key"], encrypted)
        if configuration == "missing":
            assert listing.json()[0]["can_reveal"] is False
