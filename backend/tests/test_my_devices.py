"""issue #65 slice 6a — owner-facing "My Devices" routes.

App-token, owner-only ``/api/ledgers/{ledger_id}/devices`` list / rename / revoke
+ pairing-code generation. These are the account-owner equivalents of the
loopback ``/api/admin/devices`` routes (a normal owner could not manage devices
from the app before). Asserts: list marks the caller's own device + scopes to the
ledger; rename/revoke work; revoke-current is blocked (409); pairing-code mints;
every route rejects no-auth (401), a viewer (403), and the wrong ledger (404).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, LedgerMember
from app.services.identity_service import hash_secret, new_session_token
from app.services.time_service import now_utc


def _seed_viewer_token(ledger_id: str = "owner") -> str:
    """A viewer-role app token bound to the ledger — to assert owner-only 403."""
    token = new_session_token()
    now = now_utc()
    with SessionLocal() as db:
        account = Account(display_name="viewer person", created_at=now)
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="viewer", created_at=now))
        device = Device(account_id=account.id, device_name="viewer phone", platform="android", created_at=now)
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
                created_at=now,
            )
        )
        db.commit()
    return token


def _seed_member_device(ledger_id: str = "owner") -> str:
    """Another account's device, member of + linked to the ledger. Returns its public_id."""
    now = now_utc()
    with SessionLocal() as db:
        account = Account(display_name="family member", created_at=now)
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="member", created_at=now))
        device = Device(account_id=account.id, device_name="member phone", platform="android", created_at=now)
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(new_session_token()),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
                created_at=now,
            )
        )
        db.commit()
        return device.public_id


def _devices(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get("/api/ledgers/owner/devices", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["devices"]


def test_list_my_devices_marks_current_and_hides_internal_ids(client: TestClient, *, identity) -> None:
    devices = _devices(client, identity.app_headers)
    assert len(devices) >= 1
    current = [d for d in devices if d["is_current"]]
    assert len(current) == 1, "exactly the caller's own device is marked is_current"
    for device in devices:
        assert "id" not in device, "no internal pkey leak"
        assert "token_hash" not in device
        assert "account_name" not in device, "owner view is account-scoped, no cross-account field"
        # public_id is a uuid, not the autoincrement id
        assert len(device["public_id"]) >= 32


def test_rename_my_device_updates_name(client: TestClient, *, identity) -> None:
    target = _devices(client, identity.app_headers)[0]
    response = client.post(
        f"/api/ledgers/owner/devices/{target['public_id']}/rename",
        headers=identity.app_headers,
        json={"device_name": "客厅的平板"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["device_name"] == "客厅的平板"


def test_revoke_other_device_marks_it_revoked(client: TestClient, *, identity) -> None:
    others = [d for d in _devices(client, identity.app_headers) if not d["is_current"]]
    assert others, "the bootstrap created at least one non-current device in the ledger"
    response = client.post(
        f"/api/ledgers/owner/devices/{others[0]['public_id']}/revoke",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["revoked_at"] is not None


def test_cannot_revoke_the_current_device(client: TestClient, *, identity) -> None:
    current = [d for d in _devices(client, identity.app_headers) if d["is_current"]][0]
    response = client.post(
        f"/api/ledgers/owner/devices/{current['public_id']}/revoke",
        headers=identity.app_headers,
    )
    assert response.status_code == 409, response.text


def test_owner_revokes_another_members_device_in_the_ledger(client: TestClient, *, identity) -> None:
    # issue #65 slice 6a review (F-doc): scope is the LEDGER, not the owner's own
    # account — a ledger owner CAN revoke another member's device's access to
    # their ledger (intended ledger-admin authority). Pin it so a future "restrict
    # to same account" change can't silently break this.
    member_device = _seed_member_device("owner")
    listed = [d["public_id"] for d in _devices(client, identity.app_headers)]
    assert member_device in listed, "a member's device linked to this ledger is visible to the owner"

    response = client.post(
        f"/api/ledgers/owner/devices/{member_device}/revoke", headers=identity.app_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["revoked_at"] is not None
    assert response.json()["is_current"] is False


def test_create_pairing_code_returns_a_code(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={"device_name_hint": "新平板", "ttl_minutes": 15},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pairing_code"]
    assert body["expires_at"]


def test_my_device_routes_require_auth(client: TestClient, *, identity) -> None:
    # No Authorization header → 401 on every route (strict-401 lane).
    assert client.get("/api/ledgers/owner/devices").status_code == 401
    assert client.post("/api/ledgers/owner/devices/some-id/rename", json={"device_name": "x"}).status_code == 401
    assert client.post("/api/ledgers/owner/devices/some-id/revoke").status_code == 401
    assert client.post("/api/ledgers/owner/devices/pairing-codes", json={}).status_code == 401


def test_my_device_routes_reject_a_viewer(client: TestClient, *, identity) -> None:
    viewer = {"Authorization": f"Bearer {_seed_viewer_token('owner')}"}
    assert client.get("/api/ledgers/owner/devices", headers=viewer).status_code == 403
    assert client.post(
        "/api/ledgers/owner/devices/some-id/rename", headers=viewer, json={"device_name": "x"}
    ).status_code == 403
    assert client.post("/api/ledgers/owner/devices/some-id/revoke", headers=viewer).status_code == 403
    assert client.post("/api/ledgers/owner/devices/pairing-codes", headers=viewer, json={}).status_code == 403


def test_my_device_routes_reject_wrong_ledger(client: TestClient, *, identity) -> None:
    # The owner app token is bound to ledger "owner"; asking about a different
    # ledger path must 404 (path-ledger binding), not leak another ledger.
    response = client.get("/api/ledgers/tester_1/devices", headers=identity.app_headers)
    assert response.status_code == 404, response.text
