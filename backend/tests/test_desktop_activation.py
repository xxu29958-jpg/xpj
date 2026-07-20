"""Desktop two-phase credential: a staged pending token can only activate.

Pins the entry-level contract: ``desktop_pending`` credentials are rejected by
every ordinary auth surface (business routes, /api/auth/check, refresh, admin),
and the activate endpoint is the only way forward — once, or as the canonical
replay of the committed result after a response loss. Lineage/predecessor
convergence lives in ``test_desktop_activation_lineage.py``.
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
from tests.desktop_activation_support import (
    activate as _activate,
)
from tests.desktop_activation_support import (
    attempt_row as _attempt_row,
)
from tests.desktop_activation_support import (
    live_tokens as _live_tokens,
)
from tests.desktop_activation_support import (
    pair_desktop as _pair_desktop,
)
from tests.desktop_activation_support import (
    token_row as _token_row,
)
from tests.pairing_test_support import (
    invitation_accept_payload,
    pairing_payload,
    session_refresh_payload,
)


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


def test_desktop_invitation_is_refused(identity, client: TestClient) -> None:
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
    # A new desktop session via invitation would bypass the WinCred staging
    # ceremony; it is refused without consuming the invitation.
    assert accept.status_code == 422
    assert accept.json()["error"] == "desktop_invitation_not_supported"

    accept_android = client.post(
        "/api/invitations/accept",
        json=invitation_accept_payload(
            invitation.json()["invite_token"],
            account_name="pytest-second",
            device_name="pytest-second-android",
            platform="android",
        ),
    )
    assert accept_android.status_code < 300, accept_android.text


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
