"""Pairing capabilities follow the lifecycle of their issuing/target Device."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Device, PairingCode
from app.services.identity_service import hash_pairing_code
from tests.pairing_test_support import pairing_payload
from tests.test_my_devices import (
    _auth_headers,
    _devices,
    _seed_same_account_device,
    _seed_same_account_device_session,
)


def test_revoking_device_invalidates_existing_recovery_code_and_allows_delete(
    client: TestClient,
    *,
    identity,
) -> None:
    public_id = _seed_same_account_device(identity.app_token)
    code = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=identity.app_headers,
        json={"recovery_device_public_id": public_id},
    )
    assert code.status_code == 201, code.text

    revoked = client.post(
        f"/api/ledgers/owner/devices/{public_id}/revoke",
        headers=identity.app_headers,
    )
    assert revoked.status_code == 200, revoked.text
    rejected = client.post(
        "/api/auth/pair",
        json=pairing_payload(code.json()["pairing_code"]),
    )
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["error"] == "invalid_pairing_code"

    with SessionLocal() as db:
        device_id = db.scalar(select(Device.id).where(Device.public_id == public_id))
        pairing = db.scalar(
            select(PairingCode).where(PairingCode.recovery_device_id == device_id)
        )
        assert pairing is not None
        assert pairing.revoked_at is not None

    deleted = client.post(
        f"/api/ledgers/owner/devices/{public_id}/delete",
        headers=identity.app_headers,
    )
    assert deleted.status_code == 204, deleted.text


def test_revoking_device_invalidates_pairing_codes_it_issued(
    client: TestClient,
    *,
    identity,
) -> None:
    public_id, device_token = _seed_same_account_device_session(identity.app_token)
    code = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=_auth_headers(device_token),
        json={"device_name_hint": "不再可信的新设备"},
    )
    assert code.status_code == 201, code.text
    device_count_before = len(_devices(client, identity.app_headers))

    revoked = client.post(
        f"/api/ledgers/owner/devices/{public_id}/revoke",
        headers=identity.app_headers,
    )
    assert revoked.status_code == 200, revoked.text
    rejected = client.post(
        "/api/auth/pair",
        json=pairing_payload(code.json()["pairing_code"]),
    )
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["error"] == "invalid_pairing_code"
    assert len(_devices(client, identity.app_headers)) == device_count_before

    with SessionLocal() as db:
        pairing = db.scalar(
            select(PairingCode).where(
                PairingCode.code_hash == hash_pairing_code(code.json()["pairing_code"])
            )
        )
        issuer = db.scalar(select(Device.id).where(Device.public_id == public_id))
        assert pairing is not None
        assert pairing.created_by_device_id == issuer
        assert pairing.revoked_at is not None
