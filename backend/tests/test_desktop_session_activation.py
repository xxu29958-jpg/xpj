"""Desktop pending -> durable local recovery -> activation contracts."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    Ledger,
    LedgerMember,
    PairingCode,
)
from app.services.desktop_session_service import activate_desktop_session
from app.services.identity_service import hash_pairing_code, hash_secret
from app.services.session_lifecycle_service import new_pairing_code
from app.services.time_service import ensure_utc, now_utc


def _new_code(client: TestClient, identity) -> str:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 200, response.text
    return response.json()["pairing_code"]


def _prepare_pair(
    client: TestClient,
    identity,
    *,
    code: str | None = None,
    name: str = "pytest Desktop",
) -> tuple[str, dict]:
    response = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": code or _new_code(client, identity),
            "device_name": name,
            "platform": "desktop",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["activation_required"] is True
    assert payload["activation_expires_at"]
    return payload["session_token"], payload


def _activate(
    client: TestClient,
    token: str,
    previous: str | None = None,
):
    headers = {"Authorization": f"Bearer {token}"}
    if previous is not None:
        headers["X-Ticketbox-Previous-Session"] = previous
    return client.post("/api/auth/desktop/activate", headers=headers)


def _activate_service(
    token: str,
    previous: str | None = None,
):
    with SessionLocal() as db:
        return activate_desktop_session(
            db,
            token_value=token,
            previous_token_value=previous,
        )


def _auth_check(client: TestClient, token: str):
    return client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {token}"},
    )


def _desktop_admin_ledger(client: TestClient, identity) -> str:
    device_rows = client.get(
        "/api/admin/devices",
        headers=identity.admin_headers,
    ).json()
    desktop_row = next(row for row in device_rows if row["device_name"] == "pytest Desktop")
    return desktop_row["ledger_id"]


def test_desktop_pair_is_short_pending_and_ordinary_bearer_rejects_it(
    client: TestClient,
    *,
    identity,
) -> None:
    token, payload = _prepare_pair(client, identity)

    assert (
        client.get(
            "/api/auth/check",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/expenses/pending",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 401
    )
    assert client.post("/api/auth/desktop/activate").status_code == 401
    assert client.post("/api/ledgers/owner/switch/prepare").status_code == 401
    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token)).one()
        assert row.activation_state == "pending"
        assert row.revoked_at is None
        assert row.token_hash != token
        remaining = (ensure_utc(row.expires_at) - now_utc()).total_seconds()
        assert 0 < remaining <= 5 * 60
        assert payload["activation_expires_at"].endswith("Z")


def test_pair_activation_revokes_exact_cross_device_predecessor_and_replays(
    client: TestClient,
    *,
    identity,
) -> None:
    first, _ = _prepare_pair(client, identity, name="Desktop A")
    assert _activate(client, first).status_code == 200
    second, _ = _prepare_pair(client, identity, name="Desktop B")

    # Prepare B never displaces A.
    assert (
        client.get(
            "/api/auth/check",
            headers={"Authorization": f"Bearer {first}"},
        ).status_code
        == 200
    )
    activated = _activate(client, second, first)
    assert activated.status_code == 200, activated.text
    assert activated.json()["activation_required"] is False
    assert (
        client.get(
            "/api/auth/check",
            headers={"Authorization": f"Bearer {first}"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/auth/check",
            headers={"Authorization": f"Bearer {second}"},
        ).status_code
        == 200
    )

    # Simulate a committed activation whose HTTP response was lost.
    replay = _activate(client, second, first)
    assert replay.status_code == 200
    assert replay.json() == activated.json()


def test_switch_prepare_preserves_a_then_activation_atomically_replaces_it(
    client: TestClient,
    *,
    identity,
) -> None:
    active, active_payload = _prepare_pair(client, identity)
    assert _activate(client, active).status_code == 200
    with SessionLocal() as db:
        active_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(active)).one()
        # Exercise migrated/legacy active rows that have never recorded use:
        # pending B must not win merely because it has the newer row id.
        active_row.last_used_at = None
        db.commit()
    created = client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "Desktop target"},
    )
    target = created.json()["ledger_id"]

    direct = client.post(
        f"/api/ledgers/{target}/switch",
        headers={"Authorization": f"Bearer {active}"},
    )
    assert direct.status_code == 409
    assert direct.json()["error"] == "desktop_activation_required"
    assert _auth_check(client, active).status_code == 200

    prepared = client.post(
        f"/api/ledgers/{target}/switch/prepare",
        headers={"Authorization": f"Bearer {active}"},
    )
    assert prepared.status_code == 200, prepared.text
    pending = prepared.json()["session_token"]
    assert prepared.json()["activation_required"] is True
    assert _auth_check(client, active).status_code == 200
    assert _auth_check(client, pending).status_code == 401
    assert _desktop_admin_ledger(client, identity) == active_payload["ledger_id"]

    activated = _activate(client, pending, active)
    assert activated.status_code == 200, activated.text
    assert activated.json()["ledger_id"] == target
    assert _auth_check(client, active).status_code == 401
    check = _auth_check(client, pending)
    assert check.status_code == 200
    assert check.json()["ledger_id"] == target
    assert _desktop_admin_ledger(client, identity) == target


def test_activation_expiry_stale_previous_and_same_token_are_fail_closed(
    client: TestClient,
    *,
    identity,
) -> None:
    expired, _ = _prepare_pair(client, identity)
    with SessionLocal() as db:
        row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(expired)).one()
        row.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
    assert _activate(client, expired, "tbx-cleaned-stale-wincred").status_code == 401

    for malformed_expiry in ("missing", "overlong"):
        malformed, _ = _prepare_pair(client, identity)
        with SessionLocal() as db:
            row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(malformed)).one()
            row.expires_at = (
                None if malformed_expiry == "missing" else ensure_utc(row.created_at) + timedelta(minutes=6)
            )
            db.commit()
        with pytest.raises(AppError) as error:
            _activate_service(malformed, "tbx-cleaned-stale-wincred")
        assert error.value.error == "invalid_token"
        assert error.value.status_code == 401

    pending, _ = _prepare_pair(client, identity)
    same = _activate(client, pending, pending)
    assert same.status_code == 409
    assert same.json()["error"] == "desktop_identity_rotation_required"
    assert (
        client.get(
            "/api/auth/check",
            headers={"Authorization": f"Bearer {pending}"},
        ).status_code
        == 401
    )

    # A cleaned local predecessor is only an optional revoke target.  Pairing
    # code possession still authorizes B, so stale WinCred cannot deadlock.
    recovered = _activate(client, pending, "tbx-cleaned-stale-wincred")
    assert recovered.status_code == 200, recovered.text


def test_cross_account_pair_activation_can_revoke_exact_previous_desktop(
    client: TestClient,
    *,
    identity,
) -> None:
    previous, _ = _prepare_pair(client, identity, name="old account Desktop")
    assert _activate(client, previous).status_code == 200

    code = new_pairing_code()
    with SessionLocal() as db:
        account = Account(display_name="另一个账号")
        db.add(account)
        db.flush()
        ledger = Ledger(
            ledger_id="other_account",
            name="另一个账本",
            owner_account_id=account.id,
        )
        db.add(ledger)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id=ledger.ledger_id,
                account_id=account.id,
                role="owner",
            )
        )
        db.add(
            PairingCode(
                code_hash=hash_pairing_code(code),
                ledger_id=ledger.ledger_id,
                account_id=account.id,
                expires_at=now_utc() + timedelta(minutes=15),
            )
        )
        db.commit()

    replacement, _ = _prepare_pair(
        client,
        identity,
        code=code,
        name="new account Desktop",
    )
    activated = _activate(client, replacement, previous)
    assert activated.status_code == 200, activated.text
    assert activated.json()["ledger_id"] == "other_account"
    assert (
        client.get(
            "/api/auth/check",
            headers={"Authorization": f"Bearer {previous}"},
        ).status_code
        == 401
    )
