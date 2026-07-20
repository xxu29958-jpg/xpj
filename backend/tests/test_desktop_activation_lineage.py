"""Desktop activation lineage: predecessor binding and family convergence.

The presented predecessor must share the staged credential's account and
ledger on a desktop device; a graced predecessor counts as in-flight, so the
activation closes the whole refresh lineage (current family head) with the
same rotation grace — never a second authorized family.
"""

from __future__ import annotations

import secrets as secrets_module
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, LedgerMember
from app.services.desktop_activation_service import stage_desktop_pending_token
from app.services.session_lifecycle_service import hash_secret, new_session_token
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
from tests.pairing_test_support import session_refresh_payload


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
    # A second account holding its own live desktop token, seeded directly
    # (the invitation flow refuses new desktop sessions by design).
    with SessionLocal() as db:
        account = Account(display_name="pytest-second")
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=account.id, role="member"))
        device = Device(account_id=account.id, device_name="pytest-second-desktop", platform="desktop")
        db.add(device)
        db.flush()
        foreign_token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(foreign_token),
                account_id=account.id,
                device_id=device.id,
                ledger_id="owner",
                scope="app",
            )
        )
        db.commit()

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


def test_activation_closes_refreshed_family_head(identity, client: TestClient) -> None:
    first_payload, _ = _pair_desktop(client, identity.pairing_code)
    first = _activate(client, first_payload)
    assert first.status_code == 200, first.text
    a1 = first.json()["session_token"]

    # A1 rotates to A2: A1 enters rotation grace, A2 becomes the family head.
    refresh = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {a1}"},
        json=session_refresh_payload(),
    )
    assert refresh.status_code == 200, refresh.text
    a2 = refresh.json()["session_token"]
    assert a2 != a1

    code = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={},
    )
    assert code.status_code == 201, code.text
    second_payload, _ = _pair_desktop(client, code.json()["pairing_code"])

    # Presenting the graced A1 must close the whole lineage: A2 (the current
    # family head) is superseded with rotation grace, and the receipt records
    # the head as the predecessor — not the presented stale credential.
    response = _activate(client, second_payload, previous=a1)
    assert response.status_code == 200, response.text
    a2_row = _token_row(a2)
    assert a2_row.revoked_at is not None
    assert a2_row.grace_until is not None
    assert _attempt_row(second_payload["pairing_attempt_id"]).previous_token_id == a2_row.id

    # Canonical replay does not rotate a second time.
    replay = _activate(client, second_payload, previous=a1)
    assert replay.status_code == 200, replay.text
    assert replay.json()["activated"] is False
    assert replay.json()["session_token"] == response.json()["session_token"]

    b_row = _token_row(response.json()["session_token"])
    assert b_row.scope == "app"
    assert b_row.revoked_at is None


def test_refresh_after_activation_fails_closed(identity, client: TestClient) -> None:
    first_payload, _ = _pair_desktop(client, identity.pairing_code)
    first = _activate(client, first_payload)
    assert first.status_code == 200, first.text
    a1 = first.json()["session_token"]

    code = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={},
    )
    assert code.status_code == 201, code.text
    second_payload, _ = _pair_desktop(client, code.json()["pairing_code"])
    activated = _activate(client, second_payload, previous=a1)
    assert activated.status_code == 200, activated.text

    # The superseded predecessor may finish in-flight reads during grace, but
    # it can never rotate a successor: both refresh paths refuse closed.
    headers = {"Authorization": f"Bearer {a1}"}
    assert client.post("/api/auth/refresh", headers=headers).status_code == 401
    assert client.post("/api/auth/refresh", headers=headers, json=session_refresh_payload()).status_code == 401

    # Activation replay stays canonical; no orphan pending, no second family.
    replay = _activate(client, second_payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["activated"] is False
