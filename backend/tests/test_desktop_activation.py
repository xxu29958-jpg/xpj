"""Desktop two-phase credential: a staged pending token can only activate.

Pins the entry-level contract: ``desktop_pending`` credentials are rejected by
every ordinary auth surface (business routes, /api/auth/check, refresh, admin),
and the activate endpoint is the only way forward — once, or as the canonical
replay of the committed result after a response loss.
"""

from __future__ import annotations

import secrets as secrets_module
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import AuthToken, DesktopActivationAttempt
from app.services.desktop_activation_service import (
    DESKTOP_PENDING_SCOPE,
    DESKTOP_PENDING_TOKEN_TTL_SECONDS,
    activate_desktop_session,
    stage_desktop_pending_token,
)
from app.services.session_lifecycle_service import (
    derive_desktop_activation_token,
    hash_secret,
)
from app.services.time_service import ensure_utc, now_utc
from tests.pairing_test_support import (
    invitation_accept_payload,
    pairing_payload,
    session_refresh_payload,
)


def _pair_desktop(client: TestClient, pairing_code: str, **overrides) -> tuple[dict, dict]:
    payload = pairing_payload(pairing_code, device_name="pytest-desktop", platform="desktop", **overrides)
    response = client.post("/api/auth/pair", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


def _activate(client: TestClient, payload: dict, *, previous: str | None = None):
    body = {
        "activation_attempt_id": payload["pairing_attempt_id"],
        "activation_attempt_secret": payload["pairing_attempt_secret"],
    }
    headers = {"X-Ticketbox-Previous-Session": previous} if previous else None
    return client.post("/api/auth/desktop/activate", json=body, headers=headers)


def _token_row(token_value: str) -> AuthToken:
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value)))
        assert row is not None
        db.expunge(row)
        return row


def _attempt_row(public_id: str) -> DesktopActivationAttempt:
    with SessionLocal() as db:
        row = db.scalar(select(DesktopActivationAttempt).where(DesktopActivationAttempt.public_id == public_id))
        assert row is not None
        db.expunge(row)
        return row


def _live_tokens(device_id: int, scope: str) -> list[AuthToken]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuthToken)
            .where(AuthToken.device_id == device_id)
            .where(AuthToken.scope == scope)
            .where(AuthToken.revoked_at.is_(None))
        ).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def test_desktop_pair_stages_pending_credential(identity, client: TestClient) -> None:
    payload, body = _pair_desktop(client, identity.pairing_code)

    assert body["activation_required"] is True
    assert body["activation_expires_at"] is not None
    assert body["session_token"] == derive_desktop_activation_token(
        payload["pairing_attempt_secret"],
        payload["pairing_attempt_id"],
    )

    row = _token_row(body["session_token"])
    assert row.scope == DESKTOP_PENDING_SCOPE
    assert row.revoked_at is None
    remaining = ensure_utc(row.expires_at) - now_utc()
    assert timedelta(seconds=DESKTOP_PENDING_TOKEN_TTL_SECONDS - 30) < remaining
    assert remaining <= timedelta(seconds=DESKTOP_PENDING_TOKEN_TTL_SECONDS)

    attempt = _attempt_row(payload["pairing_attempt_id"])
    assert attempt.token_id == row.id
    assert attempt.activated_at is None
    assert attempt.previous_token_id is None
    assert attempt.account_id == row.account_id
    assert attempt.device_id == row.device_id
    assert attempt.ledger_id == row.ledger_id


def test_pending_credential_rejected_by_ordinary_surfaces(identity, client: TestClient) -> None:
    _, body = _pair_desktop(client, identity.pairing_code)
    headers = {"Authorization": f"Bearer {body['session_token']}"}

    assert client.get("/api/auth/check", headers=headers).status_code == 401
    assert client.get("/api/expenses/pending", headers=headers).status_code == 401
    assert client.get("/api/ledgers", headers=headers).status_code == 401
    assert client.post("/api/bootstrap/pairing-codes", headers=headers, json={}).status_code == 401


def test_pending_credential_cannot_refresh(identity, client: TestClient) -> None:
    _, body = _pair_desktop(client, identity.pairing_code)
    headers = {"Authorization": f"Bearer {body['session_token']}"}

    # Legacy no-body path and attempt-proof path must both refuse the pending
    # credential: pending never mints a normal session through refresh.
    assert client.post("/api/auth/refresh", headers=headers).status_code == 401
    assert (
        client.post("/api/auth/refresh", headers=headers, json=session_refresh_payload()).status_code == 401
    )


def test_activate_promotes_same_value_and_grants_session(identity, client: TestClient) -> None:
    payload, body = _pair_desktop(client, identity.pairing_code)

    response = _activate(client, payload)
    assert response.status_code == 200, response.text
    activated = response.json()
    assert activated["activated"] is True
    # #218 contract: the activated session is the same value the Manager staged.
    assert activated["session_token"] == body["session_token"]
    assert activated["device_public_id"] == body["device_public_id"]

    row = _token_row(body["session_token"])
    assert row.scope == "app"
    assert row.revoked_at is None

    attempt = _attempt_row(payload["pairing_attempt_id"])
    assert attempt.activated_at is not None

    check = client.get("/api/auth/check", headers={"Authorization": f"Bearer {body['session_token']}"})
    assert check.status_code == 200, check.text
    assert check.json()["device_public_id"] == body["device_public_id"]


def test_activate_replay_returns_canonical_result(identity, client: TestClient) -> None:
    payload, _ = _pair_desktop(client, identity.pairing_code)
    first = _activate(client, payload)
    assert first.status_code == 200, first.text
    second = _activate(client, payload)
    assert second.status_code == 200, second.text

    assert first.json()["activated"] is True
    assert second.json()["activated"] is False
    assert second.json()["session_token"] == first.json()["session_token"]

    row = _token_row(first.json()["session_token"])
    assert _live_tokens(row.device_id, "app") != []
    assert len(_live_tokens(row.device_id, "app")) == 1
    assert _live_tokens(row.device_id, DESKTOP_PENDING_SCOPE) == []


def test_activate_rejects_wrong_secret_and_unknown_attempt(identity, client: TestClient) -> None:
    payload, body = _pair_desktop(client, identity.pairing_code)

    wrong_secret = {
        "activation_attempt_id": payload["pairing_attempt_id"],
        "activation_attempt_secret": secrets_module.token_urlsafe(32),
    }
    assert client.post("/api/auth/desktop/activate", json=wrong_secret).status_code == 401
    unknown = {
        "activation_attempt_id": str(uuid4()),
        "activation_attempt_secret": payload["pairing_attempt_secret"],
    }
    assert client.post("/api/auth/desktop/activate", json=unknown).status_code == 401

    # The staged credential survives failed proofs and can still activate.
    response = _activate(client, payload)
    assert response.status_code == 200, response.text
    assert response.json()["session_token"] == body["session_token"]


def test_expired_pending_is_revoked_and_never_activates(identity, client: TestClient) -> None:
    payload, body = _pair_desktop(client, identity.pairing_code)
    past = now_utc() - timedelta(seconds=1)
    with SessionLocal() as db:
        db.execute(
            update(AuthToken)
            .where(AuthToken.token_hash == hash_secret(body["session_token"]))
            .values(expires_at=past)
        )
        db.execute(
            update(DesktopActivationAttempt)
            .where(DesktopActivationAttempt.public_id == payload["pairing_attempt_id"])
            .values(expires_at=past)
        )
        db.commit()

    assert _activate(client, payload).status_code == 401
    row = _token_row(body["session_token"])
    assert row.revoked_at is not None
    assert row.scope == DESKTOP_PENDING_SCOPE
    # Fail-closed is terminal: replaying cannot revive the staged credential.
    assert _activate(client, payload).status_code == 401


def test_previous_header_equal_to_pending_is_409(identity, client: TestClient) -> None:
    payload, body = _pair_desktop(client, identity.pairing_code)

    response = _activate(client, payload, previous=body["session_token"])
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "desktop_identity_rotation_required"

    assert _activate(client, payload).status_code == 200


def test_activate_supersedes_previous_desktop_token_with_grace(identity, client: TestClient) -> None:
    first_payload, _ = _pair_desktop(client, identity.pairing_code)
    first = _activate(client, first_payload)
    assert first.status_code == 200, first.text
    previous_token = first.json()["session_token"]

    recovery = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={},
    )
    assert recovery.status_code == 201, recovery.text
    second_payload, _ = _pair_desktop(client, recovery.json()["pairing_code"])

    response = _activate(client, second_payload, previous=previous_token)
    assert response.status_code == 200, response.text

    previous_row = _token_row(previous_token)
    assert previous_row.revoked_at is not None
    assert previous_row.grace_until is not None
    assert ensure_utc(previous_row.grace_until) > now_utc()

    attempt = _attempt_row(second_payload["pairing_attempt_id"])
    assert attempt.previous_token_id == previous_row.id

    # #213 rotation grace: the superseded predecessor finishes in-flight work.
    check = client.get("/api/auth/check", headers={"Authorization": f"Bearer {previous_token}"})
    assert check.status_code == 200, check.text


def test_cross_ledger_previous_is_refused_and_untouched(identity, client: TestClient) -> None:
    first_payload, _ = _pair_desktop(client, identity.pairing_code)
    first = _activate(client, first_payload)
    assert first.status_code == 200, first.text
    foreign_token = first.json()["session_token"]

    # Stage a new desktop pending on the other ledger (same account).
    code = client.post(
        "/api/ledgers/tester_1/devices/pairing-codes",
        headers=identity.gray_app_headers,
        json={},
    )
    assert code.status_code == 201, code.text
    second_payload, _ = _pair_desktop(client, code.json()["pairing_code"])

    # A live desktop token from another ledger is a foreign credential, not
    # a predecessor: refused, never revoked, never recorded as lineage.
    response = _activate(client, second_payload, previous=foreign_token)
    assert response.status_code == 401
    assert _token_row(foreign_token).revoked_at is None
    assert _attempt_row(second_payload["pairing_attempt_id"]).previous_token_id is None

    # A wrong previous does not poison the staged credential.
    assert _activate(client, second_payload).status_code == 200


def test_cross_account_previous_is_refused_and_untouched(identity, client: TestClient) -> None:
    # A second account joins the "owner" ledger via invitation (single-phase
    # non-Manager flow) and holds its own active desktop token.
    invitation = client.post(
        "/api/ledgers/owner/invitations",
        headers=identity.app_headers,
        json={"role": "member"},
    )
    assert invitation.status_code == 201, invitation.text
    accept = client.post(
        "/api/invitations/accept",
        json=invitation_accept_payload(
            invitation.json()["invite_token"],
            account_name="pytest-second",
            device_name="pytest-second-desktop",
            platform="desktop",
        ),
    )
    assert accept.status_code < 300, accept.text
    foreign_token = accept.json()["session_token"]

    code = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={},
    )
    assert code.status_code == 201, code.text
    second_payload, _ = _pair_desktop(client, code.json()["pairing_code"])

    # A live desktop token from another account is refused, never revoked,
    # never recorded — and the staged credential still activates afterwards.
    response = _activate(client, second_payload, previous=foreign_token)
    assert response.status_code == 401
    assert _token_row(foreign_token).revoked_at is None
    assert _attempt_row(second_payload["pairing_attempt_id"]).previous_token_id is None
    assert _activate(client, second_payload).status_code == 200


def test_activate_supersedes_same_slot_active_token(identity, client: TestClient) -> None:
    first_payload, _ = _pair_desktop(client, identity.pairing_code)
    first = _activate(client, first_payload)
    assert first.status_code == 200, first.text
    previous_token = first.json()["session_token"]

    attempt_id = str(uuid4())
    secret = secrets_module.token_urlsafe(32)
    with SessionLocal() as db:
        previous_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(previous_token)))
        assert previous_row is not None
        stage_desktop_pending_token(
            db,
            account_id=previous_row.account_id,
            device_id=previous_row.device_id,
            ledger_id=previous_row.ledger_id,
            attempt_public_id=attempt_id,
            activation_secret=secret,
        )
        db.commit()

    response = client.post(
        "/api/auth/desktop/activate",
        json={"activation_attempt_id": attempt_id, "activation_attempt_secret": secret},
    )
    assert response.status_code == 200, response.text

    previous_row = _token_row(previous_token)
    assert previous_row.revoked_at is not None
    assert previous_row.grace_until is not None

    new_row = _token_row(response.json()["session_token"])
    assert new_row.scope == "app"
    assert new_row.device_id == previous_row.device_id

    attempt = _attempt_row(attempt_id)
    assert attempt.previous_token_id == previous_row.id


def test_pair_replay_before_activation_returns_same_pending(identity, client: TestClient) -> None:
    payload = pairing_payload(
        identity.pairing_code,
        device_name="pytest-desktop",
        platform="desktop",
    )
    first = client.post("/api/auth/pair", json=payload)
    second = client.post("/api/auth/pair", json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    assert first.json()["activation_required"] is True
    assert second.json()["activation_required"] is True
    assert second.json()["session_token"] == first.json()["session_token"]
    assert second.json()["device_public_id"] == first.json()["device_public_id"]

    row = _token_row(first.json()["session_token"])
    assert _live_tokens(row.device_id, DESKTOP_PENDING_SCOPE) != []
    assert len(_live_tokens(row.device_id, DESKTOP_PENDING_SCOPE)) == 1


def test_pair_replay_after_activation_returns_canonical_session(identity, client: TestClient) -> None:
    payload = pairing_payload(
        identity.pairing_code,
        device_name="pytest-desktop",
        platform="desktop",
    )
    assert client.post("/api/auth/pair", json=payload).status_code == 200
    activated = _activate(client, payload)
    assert activated.status_code == 200, activated.text

    replay = client.post("/api/auth/pair", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["activation_required"] is False
    assert replay.json()["session_token"] == activated.json()["session_token"]

    row = _token_row(activated.json()["session_token"])
    assert len(_live_tokens(row.device_id, "app")) == 1
    assert _live_tokens(row.device_id, DESKTOP_PENDING_SCOPE) == []


def test_android_pair_still_issues_live_session(identity, client: TestClient) -> None:
    payload = pairing_payload(identity.pairing_code, device_name="pytest-android", platform="android")
    response = client.post("/api/auth/pair", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["activation_required"] is False

    token = response.json()["session_token"]
    assert _token_row(token).scope == "app"
    check = client.get("/api/auth/check", headers={"Authorization": f"Bearer {token}"})
    assert check.status_code == 200, check.text


def test_desktop_recovery_code_is_out_of_scope_for_now(identity, client: TestClient) -> None:
    _, first_body = _pair_desktop(client, identity.pairing_code)
    staged_token = first_body["session_token"]

    # Current main behavior: recovery pairing codes only target Android
    # devices. Desktop recovery is a later slice; until then a staged pending
    # is governed only by its TTL and the activate endpoint.
    recovery = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={"recovery_device_public_id": first_body["device_public_id"]},
    )
    assert recovery.status_code == 409, recovery.text
    assert recovery.json()["error"] == "device_recovery_platform_mismatch"
    assert _token_row(staged_token).revoked_at is None


@pytest.mark.real_db
def test_concurrent_activate_replays_converge(identity, client: TestClient) -> None:
    payload, _ = _pair_desktop(client, identity.pairing_code)
    barrier = Barrier(2)

    def activate_once() -> tuple[str, bool]:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            result = activate_desktop_session(
                db,
                activation_attempt_id=payload["pairing_attempt_id"],
                activation_attempt_secret=payload["pairing_attempt_secret"],
            )
            db.commit()
            return result.session_token, result.activated

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: activate_once(), range(2)))

    tokens = {token for token, _ in results}
    assert len(tokens) == 1
    assert sorted(activated for _, activated in results) == [False, True]

    row = _token_row(tokens.pop())
    assert len(_live_tokens(row.device_id, "app")) == 1
    assert _live_tokens(row.device_id, DESKTOP_PENDING_SCOPE) == []


def test_superseded_pending_never_revives(identity, client: TestClient) -> None:
    first_payload, first_body = _pair_desktop(client, identity.pairing_code)
    row = _token_row(first_body["session_token"])

    attempt_id = str(uuid4())
    secret = secrets_module.token_urlsafe(32)
    with SessionLocal() as db:
        stage_desktop_pending_token(
            db,
            account_id=row.account_id,
            device_id=row.device_id,
            ledger_id=row.ledger_id,
            attempt_public_id=attempt_id,
            activation_secret=secret,
        )
        db.commit()

    # A second staging on the same principal slot supersedes the first; the
    # superseded pending is hard-revoked and can never activate or revive.
    assert _token_row(first_body["session_token"]).revoked_at is not None
    assert _activate(client, first_payload).status_code == 401

    response = client.post(
        "/api/auth/desktop/activate",
        json={"activation_attempt_id": attempt_id, "activation_attempt_secret": secret},
    )
    assert response.status_code == 200, response.text


def test_pending_token_rows_only_store_hash(identity, client: TestClient) -> None:
    _, body = _pair_desktop(client, identity.pairing_code)
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(AuthToken)
            .where(AuthToken.token_hash == body["session_token"])
        )
    assert count == 0
