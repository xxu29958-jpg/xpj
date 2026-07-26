"""Desktop two-phase ledger switch: prepare stages, activate promotes.

Pins the 218-E staging contract: ``POST /api/ledgers/{id}/switch/prepare``
(service: :mod:`app.services.desktop_switch_service`) requires a
desktop-platform app credential, stages the client-derived
``desktop_pending`` value on the target ledger, and stays response-loss
safe — a replay with the same attempt proof returns the committed staging,
never a second credential. Promotion itself is #219's activate endpoint.
"""

from __future__ import annotations

import secrets as secrets_module
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Account,
    AuthToken,
    DesktopActivationAttempt,
    Ledger,
    LedgerMember,
)
from app.services.desktop_activation_service import (
    DESKTOP_PENDING_SCOPE,
    DESKTOP_PENDING_TOKEN_TTL_SECONDS,
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
    pair_desktop as _pair_desktop,
)
from tests.desktop_activation_support import (
    token_row as _token_row,
)


def _prepare_payload() -> dict[str, str]:
    return {
        "activation_attempt_id": str(uuid4()),
        "activation_attempt_secret": secrets_module.token_urlsafe(32),
    }


def _activate_attempt(client: TestClient, payload: dict, *, previous: str | None = None):
    """POST the switch-prepare attempt proof to #219's activate endpoint."""
    headers = {"X-Ticketbox-Previous-Session": previous} if previous else None
    return client.post("/api/auth/desktop/activate", json=payload, headers=headers)


def _desktop_session(client: TestClient, pairing_code: str) -> tuple[dict, dict[str, str]]:
    """Pair + activate a desktop device on ``owner``; return (payload, headers)."""
    payload, _ = _pair_desktop(client, pairing_code)
    response = _activate(client, payload)
    assert response.status_code == 200, response.text
    token = response.json()["session_token"]
    return payload, {"Authorization": f"Bearer {token}"}


def _create_ledger(client: TestClient, headers: dict[str, str], name: str = "桌面第二账本") -> str:
    response = client.post("/api/ledgers", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["ledger_id"])


def _prepare(client: TestClient, ledger_id: str, headers: dict[str, str], payload: dict):
    return client.post(f"/api/ledgers/{ledger_id}/switch/prepare", headers=headers, json=payload)


def _foreign_owner_ledger() -> str:
    """A live ledger the seeded owner account is NOT a member of."""
    ledger_id = f"ledger_{uuid4().hex[:12]}"
    with SessionLocal() as db:
        account = Account(display_name=f"foreign-{uuid4()}")
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id=ledger_id, name="他人账本", owner_account_id=account.id))
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="owner"))
        db.commit()
    return ledger_id


def test_switch_prepare_stages_pending_credential(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    payload = _prepare_payload()

    response = _prepare(client, target, headers, payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activation_required"] is True
    assert body["activation_expires_at"] is not None
    # The session window stays open until activation sets the real app expiry.
    assert body["expires_at"] is None
    assert body["soft_refresh_after"] is None
    assert body["session_token"] == derive_desktop_activation_token(
        payload["activation_attempt_secret"],
        payload["activation_attempt_id"],
    )
    assert body["ledger"]["ledger_id"] == target
    assert body["ledger"]["role"] == "owner"

    row = _token_row(body["session_token"])
    assert row.scope == DESKTOP_PENDING_SCOPE
    assert row.revoked_at is None
    assert row.ledger_id == target
    remaining = ensure_utc(row.expires_at) - now_utc()
    assert timedelta(seconds=DESKTOP_PENDING_TOKEN_TTL_SECONDS - 30) < remaining
    assert remaining <= timedelta(seconds=DESKTOP_PENDING_TOKEN_TTL_SECONDS)

    attempt = _attempt_row(payload["activation_attempt_id"])
    assert attempt.token_id == row.id
    assert attempt.activated_at is None
    assert attempt.account_id == row.account_id
    assert attempt.device_id == row.device_id
    assert attempt.ledger_id == target

    # The authenticated source session stays live and usable.
    check = client.get("/api/auth/check", headers=headers)
    assert check.status_code == 200, check.text


def test_switch_prepare_pending_rejected_by_ordinary_surfaces(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    body = _prepare(client, target, headers, _prepare_payload()).json()
    pending_headers = {"Authorization": f"Bearer {body['session_token']}"}

    assert client.get("/api/auth/check", headers=pending_headers).status_code == 401
    assert client.get("/api/ledgers", headers=pending_headers).status_code == 401
    assert (
        client.post(
            f"/api/ledgers/{target}/switch/prepare",
            headers=pending_headers,
            json=_prepare_payload(),
        ).status_code
        == 401
    )


def test_switch_prepare_replay_returns_canonical_staging(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    payload = _prepare_payload()

    first = _prepare(client, target, headers, payload)
    assert first.status_code == 200, first.text
    second = _prepare(client, target, headers, payload)
    assert second.status_code == 200, second.text

    assert second.json()["session_token"] == first.json()["session_token"]
    assert second.json()["activation_expires_at"] == first.json()["activation_expires_at"]

    # Exactly one attempt receipt and one live staged credential: the replay
    # committed nothing new.
    with SessionLocal() as db:
        attempts = db.scalars(
            select(DesktopActivationAttempt).where(
                DesktopActivationAttempt.public_id == payload["activation_attempt_id"]
            )
        ).all()
        assert len(attempts) == 1
        assert attempts[0].last_issued_at is not None
        live_pending = db.scalars(
            select(AuthToken)
            .where(AuthToken.device_id == attempts[0].device_id)
            .where(AuthToken.scope == DESKTOP_PENDING_SCOPE)
            .where(AuthToken.revoked_at.is_(None))
        ).all()
        assert len(live_pending) == 1


def test_switch_prepare_replay_with_foreign_secret_fails_closed(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    payload = _prepare_payload()
    assert _prepare(client, target, headers, payload).status_code == 200

    foreign = {
        "activation_attempt_id": payload["activation_attempt_id"],
        "activation_attempt_secret": secrets_module.token_urlsafe(32),
    }
    response = _prepare(client, target, headers, foreign)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    # The original staging is untouched: a failed replay never revokes it.
    original = derive_desktop_activation_token(
        payload["activation_attempt_secret"],
        payload["activation_attempt_id"],
    )
    assert _token_row(original).revoked_at is None


def test_switch_prepare_new_attempt_supersedes_stale_pending(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    stale_payload = _prepare_payload()
    fresh_payload = _prepare_payload()
    assert _prepare(client, target, headers, stale_payload).status_code == 200
    assert _prepare(client, target, headers, fresh_payload).status_code == 200

    # Hard supersede, no grace: the stale staged value never activates.
    stale = _activate_attempt(client, stale_payload)
    assert stale.status_code == 401
    fresh = _activate_attempt(client, fresh_payload)
    assert fresh.status_code == 200, fresh.text

    stale_value = derive_desktop_activation_token(
        stale_payload["activation_attempt_secret"],
        stale_payload["activation_attempt_id"],
    )
    stale_row = _token_row(stale_value)
    assert stale_row.revoked_at is not None
    assert stale_row.grace_until is None

    # Replaying the superseded prepare also fails closed.
    replay = _prepare(client, target, headers, stale_payload)
    assert replay.status_code == 401
    assert replay.json()["error"] == "invalid_token"


def test_switch_prepare_then_activate_promotes_on_target_ledger(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    payload = _prepare_payload()
    body = _prepare(client, target, headers, payload).json()

    activated = _activate_attempt(client, payload)
    assert activated.status_code == 200, activated.text
    assert activated.json()["activated"] is True
    # Same client-derived value promoted in place, now scoped to the target.
    assert activated.json()["session_token"] == body["session_token"]
    assert activated.json()["ledger_id"] == target

    row = _token_row(body["session_token"])
    assert row.scope == "app"
    assert row.ledger_id == target
    assert row.revoked_at is None

    check = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {body['session_token']}"},
    )
    assert check.status_code == 200, check.text
    assert check.json()["ledger_id"] == target

    # Activate response-loss replay returns the committed activation.
    replay = _activate_attempt(client, payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["activated"] is False
    assert replay.json()["session_token"] == body["session_token"]

    # The source-ledger session is a different slot: activation does not
    # supersede it cross-ledger; it stays usable until TTL or explicit revoke.
    source_check = client.get("/api/auth/check", headers=headers)
    assert source_check.status_code == 200, source_check.text


def test_activate_after_switch_rejects_source_ledger_previous_session(identity, client: TestClient) -> None:
    """#219's predecessor binding is same-ledger: the source session is not a
    valid X-Ticketbox-Previous-Session proof for a switch activation."""
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    payload = _prepare_payload()
    _prepare(client, target, headers, payload)
    source_token = headers["Authorization"].removeprefix("Bearer ")

    rejected = _activate_attempt(client, payload, previous=source_token)
    assert rejected.status_code == 401
    assert rejected.json()["error"] == "invalid_token"

    promoted = _activate_attempt(client, payload)
    assert promoted.status_code == 200, promoted.text


def test_switch_prepare_requires_desktop_platform(identity, client: TestClient) -> None:
    # The seeded Android owner token is a valid app credential — but not a
    # desktop one, so it must never stage a desktop switch credential.
    target = _create_ledger(client, identity.app_headers)
    payload = _prepare_payload()

    response = _prepare(client, target, identity.app_headers, payload)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(DesktopActivationAttempt).where(
                    DesktopActivationAttempt.public_id == payload["activation_attempt_id"]
                )
            )
            is None
        )


def test_switch_prepare_requires_target_membership(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    foreign = _foreign_owner_ledger()

    response = _prepare(client, foreign, headers, _prepare_payload())
    assert response.status_code == 403
    assert response.json()["error"] == "ledger_forbidden"

    missing = _prepare(client, "ledger_missing", headers, _prepare_payload())
    assert missing.status_code == 403
    assert missing.json()["error"] == "ledger_forbidden"


def test_switch_prepare_requires_auth(identity, client: TestClient) -> None:
    response = client.post(
        "/api/ledgers/owner/switch/prepare",
        json=_prepare_payload(),
    )
    assert response.status_code == 401


def test_switch_prepare_expired_attempt_replay_fails_closed(identity, client: TestClient) -> None:
    _, headers = _desktop_session(client, identity.pairing_code)
    target = _create_ledger(client, headers)
    payload = _prepare_payload()
    assert _prepare(client, target, headers, payload).status_code == 200

    # TTL passes: the staged credential and its receipt expire.
    past = now_utc() - timedelta(seconds=1)
    with SessionLocal() as db:
        value = derive_desktop_activation_token(
            payload["activation_attempt_secret"],
            payload["activation_attempt_id"],
        )
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(value)))
        assert token is not None
        token.expires_at = past
        attempt = db.scalar(
            select(DesktopActivationAttempt).where(
                DesktopActivationAttempt.public_id == payload["activation_attempt_id"]
            )
        )
        assert attempt is not None
        attempt.expires_at = past
        db.commit()

    replay = _prepare(client, target, headers, payload)
    assert replay.status_code == 401
    assert replay.json()["error"] == "invalid_token"

    # Recovery is a fresh attempt id, which stages cleanly.
    recovery = _prepare(client, target, headers, _prepare_payload())
    assert recovery.status_code == 200, recovery.text
