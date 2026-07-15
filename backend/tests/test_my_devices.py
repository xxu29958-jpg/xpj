"""Account-scoped device lifecycle and explicit same-Device recovery.

Every active member can manage their own Account's devices. A recovery pairing
code deliberately reissues one existing Device identity so its device-scoped
idempotency keys and quarantined outbox can continue; it never adopts another
Device's intent merely because the Account matches.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import (
    Account,
    AuthToken,
    Device,
    LedgerMember,
    RuleApplicationBatch,
    UploadLink,
    UploadLinkDailyUsage,
    UploadLinkRemoteAttempt,
)
from app.services.identity_service import hash_secret, new_session_token
from app.services.time_service import now_utc
from tests.pairing_test_support import pairing_payload


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def _seed_same_account_device_session(
    token_value: str,
    ledger_id: str = "owner",
    platform: str = "android",
) -> tuple[str, str]:
    now = now_utc()
    spare_token = new_session_token()
    with SessionLocal() as db:
        session = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(token_value)).one()
        device = Device(
            account_id=session.account_id,
            device_name="spare phone",
            platform=platform,
            created_at=now,
        )
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(spare_token),
                account_id=session.account_id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
                created_at=now,
            )
        )
        db.commit()
        return device.public_id, spare_token


def _seed_same_account_device(token_value: str, ledger_id: str = "owner") -> str:
    return _seed_same_account_device_session(token_value, ledger_id)[0]


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


def test_owner_cannot_revoke_another_members_global_device(
    client: TestClient,
    *,
    identity,
) -> None:
    member_device = _seed_member_device("owner")
    listed = [d["public_id"] for d in _devices(client, identity.app_headers)]
    assert member_device not in listed

    response = client.post(f"/api/ledgers/owner/devices/{member_device}/revoke", headers=identity.app_headers)
    assert response.status_code == 404, response.text


def test_delete_revoked_device_removes_it(client: TestClient, *, identity) -> None:
    # A device must be revoked first (no active in-scope binding), then deleting
    # it returns 204 and drops it from the owner's device list.
    member_device = _seed_same_account_device(identity.app_token)
    with SessionLocal() as db:
        device = db.query(Device).filter(Device.public_id == member_device).one()
        batch = RuleApplicationBatch(
            tenant_id="owner",
            status="applied",
            pending_scanned=0,
            changed_count=0,
            actor_device_id=device.id,
        )
        db.add(batch)
        link = UploadLink(
            token_hash=hash_secret(f"upload-link-{device.public_id}"),
            account_id=device.account_id,
            device_id=device.id,
            ledger_id="owner",
        )
        db.add(link)
        db.flush()
        usage = UploadLinkDailyUsage(
            upload_link_id=link.id,
            ymd="2026-07-15",
            bytes_total=1024,
            request_count=1,
        )
        attempt = UploadLinkRemoteAttempt(
            upload_link_id=link.id,
            remote_key="pytest-device-delete",
        )
        db.add_all([usage, attempt])
        db.commit()
        batch_id = batch.id
        usage_id = usage.id
        attempt_id = attempt.id
    revoke = client.post(f"/api/ledgers/owner/devices/{member_device}/revoke", headers=identity.app_headers)
    assert revoke.status_code == 200, revoke.text
    delete = client.post(f"/api/ledgers/owner/devices/{member_device}/delete", headers=identity.app_headers)
    assert delete.status_code == 204, delete.text
    assert not delete.content, "204 carries no body"
    remaining = [d["public_id"] for d in _devices(client, identity.app_headers)]
    assert member_device not in remaining, "the deleted device is gone from the list"
    with SessionLocal() as db:
        preserved_batch = db.get(RuleApplicationBatch, batch_id)
        assert preserved_batch is not None
        assert preserved_batch.actor_device_id is None
        assert db.get(UploadLinkDailyUsage, usage_id) is None
        assert db.get(UploadLinkRemoteAttempt, attempt_id) is None


def test_cannot_delete_the_current_device(client: TestClient, *, identity) -> None:
    current = [d for d in _devices(client, identity.app_headers) if d["is_current"]][0]
    response = client.post(
        f"/api/ledgers/owner/devices/{current['public_id']}/delete",
        headers=identity.app_headers,
    )
    assert response.status_code == 409, response.text


def test_cannot_delete_an_active_device(client: TestClient, *, identity) -> None:
    # An unrevoked device with an ACTIVE token in the ledger must be revoked
    # before delete (409 "请先停用"), so a live binding can't be deleted by mistake.
    member_device = _seed_same_account_device(identity.app_token)
    response = client.post(f"/api/ledgers/owner/devices/{member_device}/delete", headers=identity.app_headers)
    assert response.status_code == 409, response.text


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


def test_recovery_pairing_reuses_exact_device_and_revokes_its_old_session(
    client: TestClient,
    *,
    identity,
) -> None:
    public_id, old_token = _seed_same_account_device_session(identity.app_token)
    device_count_before = len(_devices(client, identity.app_headers))
    code_response = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={
            "device_name_hint": "待恢复手机",
            "recovery_device_public_id": public_id,
        },
    )
    assert code_response.status_code == 201, code_response.text
    request = pairing_payload(
        code_response.json()["pairing_code"],
        device_name="恢复后的手机",
    )

    wrong_platform = client.post(
        "/api/auth/pair",
        json={**request, "platform": "windows"},
    )
    assert wrong_platform.status_code == 409, wrong_platform.text
    assert wrong_platform.json()["error"] == "device_recovery_platform_mismatch"
    assert client.get("/api/auth/check", headers=_auth_headers(old_token)).status_code == 200
    with SessionLocal() as db:
        unchanged = db.query(Device).filter(Device.public_id == public_id).one()
        assert unchanged.platform == "android"

    recovered = client.post("/api/auth/pair", json=request)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["device_public_id"] == public_id
    assert len(_devices(client, identity.app_headers)) == device_count_before
    assert client.get("/api/auth/check", headers=_auth_headers(old_token)).status_code == 401
    assert (
        client.get(
            "/api/auth/check",
            headers=_auth_headers(recovered.json()["session_token"]),
        ).status_code
        == 200
    )

    replay = client.post("/api/auth/pair", json=request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["session_token"] == recovered.json()["session_token"]
    assert replay.json()["device_public_id"] == public_id

    revoke = client.post(
        f"/api/ledgers/owner/devices/{public_id}/revoke",
        headers=identity.app_headers,
    )
    assert revoke.status_code == 200, revoke.text
    delete = client.post(
        f"/api/ledgers/owner/devices/{public_id}/delete",
        headers=identity.app_headers,
    )
    assert delete.status_code == 204, delete.text


def test_recovery_pairing_rejects_current_or_other_accounts_device(
    client: TestClient,
    *,
    identity,
) -> None:
    current = next(row for row in _devices(client, identity.app_headers) if row["is_current"])
    current_response = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={"recovery_device_public_id": current["public_id"]},
    )
    assert current_response.status_code == 409

    other_device = _seed_member_device("owner")
    other_response = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={"recovery_device_public_id": other_device},
    )
    assert other_response.status_code == 404

    windows_device, _windows_token = _seed_same_account_device_session(
        identity.app_token,
        platform="windows",
    )
    wrong_platform = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={"recovery_device_public_id": windows_device},
    )
    assert wrong_platform.status_code == 409
    assert wrong_platform.json()["error"] == "device_recovery_platform_mismatch"


def test_my_device_routes_require_auth(client: TestClient, *, identity) -> None:
    # No Authorization header → 401 on every route (strict-401 lane).
    assert client.get("/api/ledgers/owner/devices").status_code == 401
    assert client.post("/api/ledgers/owner/devices/some-id/rename", json={"device_name": "x"}).status_code == 401
    assert client.post("/api/ledgers/owner/devices/some-id/revoke").status_code == 401
    assert client.post("/api/ledgers/owner/devices/some-id/delete").status_code == 401
    assert client.post("/api/ledgers/owner/devices/pairing-codes", json={}).status_code == 401


def test_viewer_can_manage_only_their_own_devices(client: TestClient, *, identity) -> None:
    viewer = {"Authorization": f"Bearer {_seed_viewer_token('owner')}"}
    listed = client.get("/api/ledgers/owner/devices", headers=viewer)
    assert listed.status_code == 200, listed.text
    devices = listed.json()["devices"]
    assert len(devices) == 1 and devices[0]["is_current"] is True
    public_id = devices[0]["public_id"]

    renamed = client.post(
        f"/api/ledgers/owner/devices/{public_id}/rename",
        headers=viewer,
        json={"device_name": "只读成员的手机"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["device_name"] == "只读成员的手机"
    assert (
        client.post(
            f"/api/ledgers/owner/devices/{public_id}/revoke",
            headers=viewer,
        ).status_code
        == 409
    )
    created = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=viewer,
        json={},
    )
    assert created.status_code == 201, created.text


def test_my_device_routes_reject_wrong_ledger(client: TestClient, *, identity) -> None:
    # The session is ledger-neutral and this Account owns both seeded ledgers.
    # Path selection therefore succeeds, but it returns the same Account devices.
    response = client.get("/api/ledgers/tester_1/devices", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    assert {row["public_id"] for row in response.json()["devices"]} == {
        row["public_id"] for row in _devices(client, identity.app_headers)
    }

    missing = client.get(
        "/api/ledgers/ledger_does_not_exist/devices",
        headers=identity.app_headers,
    )
    assert missing.status_code == 404
