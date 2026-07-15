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
from sqlalchemy import event

import app.services.session_refresh_service as session_refresh_service
from app.config import reset_settings_cache
from app.database import SessionLocal, engine
from app.models import AuthToken, Device, Ledger, LedgerMember, SessionRefreshAttempt
from app.services.identity_service import authenticate_session_token, hash_secret
from app.services.time_service import ensure_utc, now_utc
from tests.pairing_test_support import pairing_payload, session_refresh_payload


@pytest.fixture()
def ttl_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_TOKEN_TTL_DAYS", "30")
    monkeypatch.setenv("APP_TOKEN_REFRESH_WINDOW_DAYS", "7")
    monkeypatch.setenv("APP_TOKEN_ROTATION_GRACE_SECONDS", "120")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _pair(client: TestClient, *, code: str) -> dict:
    response = client.post(
        "/api/auth/pair",
        json=pairing_payload(code, device_name="pytest-rotate"),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_refresh_fails_loudly_when_replacement_is_not_persisted(
    client: TestClient,
    *,
    identity,
    ttl_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paired = _pair(client, code=identity.pairing_code)
    refresh = session_refresh_payload()
    monkeypatch.setattr(
        session_refresh_service,
        "issue_auth_token",
        lambda *args, **kwargs: "discarded-token",
    )

    with SessionLocal() as db, pytest.raises(session_refresh_service.SessionRefreshPersistenceError):
        session_refresh_service.refresh_or_recover_app_session(
            db,
            source_token_value=paired["session_token"],
            refresh_attempt_id=refresh["refresh_attempt_id"],
            refresh_attempt_secret=refresh["refresh_attempt_secret"],
        )


def test_pair_response_carries_expiry_metadata(client: TestClient, *, identity, ttl_env) -> None:
    payload = _pair(client, code=identity.pairing_code)
    assert payload["expires_at"] is not None
    assert payload["soft_refresh_after"] is not None
    expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
    soft_after = datetime.fromisoformat(payload["soft_refresh_after"].replace("Z", "+00:00"))
    now = datetime.now(UTC)
    assert expires_at > now + timedelta(days=20)
    assert expires_at > soft_after


def test_refresh_rotates_token_and_graces_previous(client: TestClient, *, identity, ttl_env) -> None:
    pair_payload = _pair(client, code=identity.pairing_code)
    old_token = pair_payload["session_token"]

    refresh = session_refresh_payload()
    response = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=refresh,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rotated"] is True
    assert body["refresh_attempt_id"] == refresh["refresh_attempt_id"]
    new_token = body["session_token"]
    assert new_token != old_token

    grace_check = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert grace_check.status_code == 200, grace_check.text

    with SessionLocal() as db:
        old_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(old_token)).one()
        new_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(new_token)).one()
        assert old_row.revoked_at is not None
        assert old_row.grace_until is not None
        assert new_row.revoked_at is None
        assert new_row.expires_at is not None

        old_row.grace_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    expired_grace = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert expired_grace.status_code == 401


def test_legacy_refresh_keeps_the_same_session_recoverable(
    client: TestClient,
    *,
    identity,
    ttl_env,
) -> None:
    old_token = _pair(client, code=identity.pairing_code)["session_token"]
    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(old_token)).one()
        row.expires_at = now_utc() + timedelta(hours=1)
        db.commit()

    first = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["session_token"] == old_token
    assert first.json()["rotated"] is False
    assert first.json()["expires_at"] is not None
    assert first.json()["soft_refresh_after"] is not None

    retry_after_response_loss = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert retry_after_response_loss.status_code == 200, retry_after_response_loss.text
    assert retry_after_response_loss.json()["session_token"] == old_token
    assert retry_after_response_loss.json()["rotated"] is False

    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(old_token)).one()
        assert row.revoked_at is None
        assert ensure_utc(row.expires_at) > now_utc() + timedelta(days=20)


def test_refresh_retry_recovers_same_token_after_grace_expires(
    client: TestClient,
    *,
    identity,
    ttl_env,
) -> None:
    old_token = _pair(client, code=identity.pairing_code)["session_token"]
    refresh = session_refresh_payload()
    first = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=refresh,
    )
    assert first.status_code == 200, first.text
    first_token = first.json()["session_token"]

    with SessionLocal() as db:
        old_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(old_token)).one()
        old_row.grace_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    retry = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=refresh,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["session_token"] == first_token
    assert retry.json()["refresh_attempt_id"] == refresh["refresh_attempt_id"]


def test_refresh_retry_replays_frozen_soft_refresh_receipt(
    client: TestClient,
    *,
    identity,
    ttl_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_token = _pair(client, code=identity.pairing_code)["session_token"]
    refresh = session_refresh_payload()
    first = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=refresh,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()

    with SessionLocal() as db:
        attempt = db.query(SessionRefreshAttempt).filter(
            SessionRefreshAttempt.public_id == refresh["refresh_attempt_id"]
        ).one()
        assert attempt.session_soft_refresh_after is not None
        old_row = db.query(AuthToken).filter(
            AuthToken.token_hash == hash_secret(old_token)
        ).one()
        old_row.grace_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    monkeypatch.setenv("APP_TOKEN_REFRESH_WINDOW_DAYS", "1")
    reset_settings_cache()
    retry = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=refresh,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["session_token"] == first_body["session_token"]
    assert retry.json()["expires_at"] == first_body["expires_at"]
    assert retry.json()["soft_refresh_after"] == first_body["soft_refresh_after"]


def test_refresh_survives_disabled_default_ledger_when_account_has_another_ledger(
    client: TestClient,
    *,
    identity,
    ttl_env,
) -> None:
    old_token = _pair(client, code=identity.pairing_code)["session_token"]
    fallback_ledger_id = "refresh-surviving-ledger"
    with SessionLocal() as db:
        token = db.query(AuthToken).filter(
            AuthToken.token_hash == hash_secret(old_token)
        ).one()
        db.add(
            Ledger(
                ledger_id=fallback_ledger_id,
                name="续期存活账本",
                owner_account_id=token.account_id,
            )
        )
        db.flush()
        db.add(
            LedgerMember(
                ledger_id=fallback_ledger_id,
                account_id=token.account_id,
                role="owner",
            )
        )
        default_membership = db.query(LedgerMember).filter(
            LedgerMember.ledger_id == token.ledger_id,
            LedgerMember.account_id == token.account_id,
        ).one()
        default_membership.disabled_at = now_utc()
        db.commit()

    refresh = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=session_refresh_payload(),
    )
    assert refresh.status_code == 200, refresh.text

    selected = client.get(
        "/api/auth/check",
        headers={
            "Authorization": f"Bearer {refresh.json()['session_token']}",
            "X-Ticketbox-Ledger-ID": fallback_ledger_id,
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["ledger_id"] == fallback_ledger_id


def test_graced_source_token_can_finish_ledger_switch_after_refresh_wins(
    client: TestClient,
    *,
    identity,
    ttl_env,
) -> None:
    old_token = _pair(client, code=identity.pairing_code)["session_token"]
    target_ledger_id = "refresh-race-target"
    with SessionLocal() as db:
        token = db.query(AuthToken).filter(
            AuthToken.token_hash == hash_secret(old_token)
        ).one()
        db.add(
            Ledger(
                ledger_id=target_ledger_id,
                name="刷新竞态账本",
                owner_account_id=token.account_id,
            )
        )
        db.flush()
        db.add(
            LedgerMember(
                ledger_id=target_ledger_id,
                account_id=token.account_id,
                role="owner",
            )
        )
        db.commit()

    proof = session_refresh_payload()
    refreshed = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=proof,
    )
    assert refreshed.status_code == 200, refreshed.text

    switched = client.post(
        f"/api/ledgers/{target_ledger_id}/switch",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["session_token"] == old_token

    selected = client.get(
        "/api/auth/check",
        headers={
            "Authorization": f"Bearer {refreshed.json()['session_token']}",
            "X-Ticketbox-Ledger-ID": target_ledger_id,
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["ledger_id"] == target_ledger_id

    replay = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=proof,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == refreshed.json()


def test_refresh_retry_rejects_a_different_proof(
    client: TestClient,
    *,
    identity,
    ttl_env,
) -> None:
    old_token = _pair(client, code=identity.pairing_code)["session_token"]
    first = session_refresh_payload()
    response = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=first,
    )
    assert response.status_code == 200, response.text

    wrong = session_refresh_payload()
    retry = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
        json=wrong,
    )
    assert retry.status_code == 401


def test_refresh_with_ttl_disabled_is_noop(client: TestClient, *, identity, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_refresh_rejects_missing_bearer(client: TestClient, *, identity, ttl_env) -> None:
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401


def test_expired_app_token_is_rejected_and_revoked(client: TestClient, *, identity, ttl_env) -> None:
    pair_payload = _pair(client, code=identity.pairing_code)
    token = pair_payload["session_token"]
    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token)).one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    response = client.get("/api/auth/check", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token)).one()
        assert row.revoked_at is not None


def test_auth_activity_refresh_is_throttled(client: TestClient, *, identity) -> None:
    token = identity.app_token
    recent = now_utc() - timedelta(seconds=30)
    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token)).one()
        device = db.get(Device, row.device_id)
        assert device is not None
        row.last_used_at = recent
        device.last_seen_at = recent
        db.commit()

    response = client.get("/api/auth/check", headers=identity.app_headers)
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token)).one()
        device = db.get(Device, row.device_id)
        assert device is not None
        assert ensure_utc(row.last_used_at) == ensure_utc(recent)
        assert ensure_utc(device.last_seen_at) == ensure_utc(recent)

        old = now_utc() - timedelta(seconds=61)
        row.last_used_at = old
        device.last_seen_at = old
        db.commit()

    response = client.get("/api/auth/check", headers=identity.app_headers)
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token)).one()
        device = db.get(Device, row.device_id)
        assert device is not None
        assert ensure_utc(row.last_used_at) is not None
        assert ensure_utc(device.last_seen_at) is not None
        assert ensure_utc(row.last_used_at) > ensure_utc(old)
        assert ensure_utc(device.last_seen_at) > ensure_utc(old)


def test_auth_context_build_uses_batched_identity_lookup(identity) -> None:
    token = identity.app_token
    recent = now_utc() - timedelta(seconds=30)
    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token)).one()
        device = db.get(Device, row.device_id)
        assert device is not None
        row.last_used_at = recent
        device.last_seen_at = recent
        db.commit()

    selects: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with SessionLocal() as db:
            ctx = authenticate_session_token(db, token, {"app"})
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

    assert ctx.ledger_id == "owner"
    assert len(selects) == 2
