"""v1.1 Batch 2: app token soft-expiry + silent rotation contract.

The ``/api/auth/refresh`` endpoint revokes the current session token and
hands back a fresh one with a new ``expires_at``. Pair responses now
also carry ``expires_at`` / ``soft_refresh_after`` so clients can decide
when to call refresh without polling.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings_cache
from app.database import SessionLocal
from app.models import AuthToken
from app.services.identity_service import hash_secret


@pytest.fixture()
def ttl_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_TOKEN_TTL_DAYS", "30")
    monkeypatch.setenv("APP_TOKEN_REFRESH_WINDOW_DAYS", "7")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _pair(client: TestClient, *, code: str) -> dict:
    response = client.post(
        "/api/auth/pair",
        json={"pairing_code": code, "device_name": "pytest-rotate", "platform": "android"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_pair_response_carries_expiry_metadata(
    client: TestClient, *, identity, ttl_env
) -> None:
    payload = _pair(client, code=identity.pairing_code)
    assert payload["expires_at"] is not None
    assert payload["soft_refresh_after"] is not None
    expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
    soft_after = datetime.fromisoformat(
        payload["soft_refresh_after"].replace("Z", "+00:00")
    )
    now = datetime.now(UTC)
    assert expires_at > now + timedelta(days=20)
    assert expires_at > soft_after


def test_refresh_rotates_token_and_revokes_previous(
    client: TestClient, *, identity, ttl_env
) -> None:
    pair_payload = _pair(client, code=identity.pairing_code)
    old_token = pair_payload["session_token"]

    response = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rotated"] is True
    new_token = body["session_token"]
    assert new_token != old_token

    # Old token must be revoked.
    with SessionLocal() as db:
        old_row = (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hash_secret(old_token))
            .one()
        )
        new_row = (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hash_secret(new_token))
            .one()
        )
        assert old_row.revoked_at is not None
        assert new_row.revoked_at is None
        assert new_row.expires_at is not None


def test_refresh_with_ttl_disabled_is_noop(
    client: TestClient, *, identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_TOKEN_TTL_DAYS", "0")
    reset_settings_cache()
    try:
        pair_payload = _pair(client, code=identity.pairing_code)
        old_token = pair_payload["session_token"]
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["rotated"] is False
        assert body["session_token"] == old_token
        assert body["expires_at"] is None
    finally:
        reset_settings_cache()


def test_refresh_rejects_missing_bearer(
    client: TestClient, *, identity, ttl_env
) -> None:
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401
