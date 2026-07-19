from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AuthToken, Device, DeviceEnrollmentAttempt, PairingCode
from app.services.identity_service import PairingResult, hash_secret, pair_device
from app.services.session_lifecycle_service import hash_pairing_code
from app.services.time_service import now_utc
from tests.pairing_test_support import pairing_payload, session_refresh_payload


def _device_identity_for_token(token_value: str) -> tuple[int, str]:
    with SessionLocal() as db:
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value)))
        assert token is not None
        device = db.get(Device, token.device_id)
        assert device is not None
        return device.id, device.public_id


def _create_recovery_pairing_code(
    client: TestClient,
    *,
    headers: dict[str, str],
    device_public_id: str,
) -> str:
    response = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers=headers,
        json={"recovery_device_public_id": device_public_id},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["pairing_code"])


def _replay_pairing_after_response_loss(request: dict[str, str]) -> list[PairingResult]:
    barrier = Barrier(2)

    def replay_once() -> PairingResult:
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            return pair_device(
                db,
                **request,
                remote_id="device-recovery-response-loss",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda _index: replay_once(), range(2)))


def _active_token_hashes(device_id: int) -> set[str]:
    with SessionLocal() as db:
        return set(
            db.scalars(
                select(AuthToken.token_hash)
                .where(AuthToken.device_id == device_id)
                .where(AuthToken.revoked_at.is_(None))
            )
        )


def _assert_recovery_receipt(
    *,
    code_a: str,
    code_b: str,
    request_b: dict[str, str],
    target_device_id: int,
    expected_token_hash: str,
) -> None:
    code_hashes = {hash_pairing_code(code_a), hash_pairing_code(code_b)}
    with SessionLocal() as db:
        pairings = {
            row.code_hash: row
            for row in db.scalars(
                select(PairingCode).where(PairingCode.code_hash.in_(code_hashes))
            )
        }
        sibling = pairings[hash_pairing_code(code_a)]
        consumed = pairings[hash_pairing_code(code_b)]
        assert sibling.used_at is None
        assert sibling.revoked_at is not None
        assert sibling.recovery_device_id is None
        assert consumed.used_at is not None
        assert consumed.revoked_at is None
        assert consumed.recovery_device_id is None
        attempt_count = db.scalar(
            select(func.count())
            .select_from(DeviceEnrollmentAttempt)
            .where(DeviceEnrollmentAttempt.public_id == request_b["pairing_attempt_id"])
        )
    assert attempt_count == 1
    assert _active_token_hashes(target_device_id) == {expected_token_hash}


def _refresh_device_session(
    client: TestClient,
    *,
    source_token: str,
    headers: dict[str, str],
) -> tuple[dict[str, str], str]:
    with SessionLocal() as db:
        source = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(source_token))
        )
        assert source is not None
        source.expires_at = now_utc() + timedelta(days=30)
        db.commit()
    proof = session_refresh_payload()
    refreshed = client.post("/api/auth/refresh", headers=headers, json=proof)
    assert refreshed.status_code == 200, refreshed.text
    return proof, str(refreshed.json()["session_token"])


def _assert_recovery_revoked_credential_family(
    client: TestClient,
    *,
    source_token: str,
    replacement_token: str,
    recovered_token: str,
    refresh_proof: dict[str, str],
) -> None:
    for stale_token in (source_token, replacement_token):
        rejected = client.get(
            "/api/auth/check",
            headers={"Authorization": f"Bearer {stale_token}"},
        )
        assert rejected.status_code == 401, rejected.text
    accepted = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {recovered_token}"},
    )
    assert accepted.status_code == 200, accepted.text
    refresh_replay = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {source_token}"},
        json=refresh_proof,
    )
    assert refresh_replay.status_code == 401, refresh_replay.text


def test_legacy_pair_requires_upgrade_without_consuming_code(
    client: TestClient,
    *,
    identity,
) -> None:
    rejected = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": identity.pairing_code,
            "device_name": "legacy-android",
            "platform": "android",
        },
    )

    assert rejected.status_code == 409
    assert rejected.json()["error"] == "client_upgrade_required"
    assert "升级" in rejected.json()["message"]

    retried = client.post(
        "/api/auth/pair",
        json=pairing_payload(identity.pairing_code, device_name="upgraded-android"),
    )
    assert retried.status_code == 200, retried.text


@pytest.mark.real_db
def test_concurrent_pairing_retries_replay_one_device_and_token(*, identity) -> None:
    request = pairing_payload(identity.pairing_code, device_name="response-loss-device")
    barrier = Barrier(2)

    def pair_once():
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            return pair_device(db, **request, remote_id="pairing-recovery-race")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: pair_once(), range(2)))

    assert results[0].session_token == results[1].session_token
    assert results[0].device_public_id == results[1].device_public_id
    with SessionLocal() as db:
        attempt_count = db.scalar(
            select(func.count())
            .select_from(DeviceEnrollmentAttempt)
            .where(DeviceEnrollmentAttempt.public_id == request["pairing_attempt_id"])
        )
        device_count = db.scalar(
            select(func.count()).select_from(Device).where(Device.public_id == results[0].device_public_id)
        )
        token_count = db.scalar(
            select(func.count())
            .select_from(AuthToken)
            .where(AuthToken.token_hash == hash_secret(results[0].session_token))
        )
    assert attempt_count == 1
    assert device_count == 1
    assert token_count == 1


@pytest.mark.real_db
def test_device_recovery_closes_sibling_codes_and_replays_one_enrollment(
    client: TestClient,
    *,
    identity,
) -> None:
    source_token = identity.tenant_app_token
    target_device_id, target_public_id = _device_identity_for_token(identity.tenant_app_token)
    code_a = _create_recovery_pairing_code(
        client,
        headers=identity.app_headers,
        device_public_id=target_public_id,
    )
    code_b = _create_recovery_pairing_code(
        client,
        headers=identity.app_headers,
        device_public_id=target_public_id,
    )
    refresh_proof, replacement_token = _refresh_device_session(
        client,
        source_token=source_token,
        headers=identity.gray_app_headers,
    )
    request_b = pairing_payload(code_b, device_name="recovered-after-response-loss")

    with SessionLocal() as db:
        first_result = pair_device(
            db,
            **request_b,
            remote_id="device-recovery-response-loss",
        )

    replayed = _replay_pairing_after_response_loss(request_b)
    expected_token_hash = hash_secret(first_result.session_token)
    assert {result.session_token for result in replayed} == {first_result.session_token}
    assert {result.device_public_id for result in replayed} == {target_public_id}
    _assert_recovery_receipt(
        code_a=code_a,
        code_b=code_b,
        request_b=request_b,
        target_device_id=target_device_id,
        expected_token_hash=expected_token_hash,
    )

    rejected_a = client.post(
        "/api/auth/pair",
        json=pairing_payload(code_a, device_name="stale-recovery-code"),
    )
    assert rejected_a.status_code == 401, rejected_a.text
    assert rejected_a.json()["error"] == "invalid_pairing_code"

    with SessionLocal() as db:
        target = db.get(Device, target_device_id)
        assert target is not None
        assert target.public_id == target_public_id
        assert target.device_name == "recovered-after-response-loss"
    assert _active_token_hashes(target_device_id) == {expected_token_hash}
    _assert_recovery_revoked_credential_family(
        client,
        source_token=source_token,
        replacement_token=replacement_token,
        recovered_token=first_result.session_token,
        refresh_proof=refresh_proof,
    )


@pytest.mark.real_db
def test_device_recovery_does_not_close_new_device_pairing_code(
    client: TestClient,
    *,
    identity,
) -> None:
    _target_device_id, target_public_id = _device_identity_for_token(identity.tenant_app_token)
    recovery_code = _create_recovery_pairing_code(
        client,
        headers=identity.app_headers,
        device_public_id=target_public_id,
    )

    recovered = client.post(
        "/api/auth/pair",
        json=pairing_payload(recovery_code, device_name="recovered-device"),
    )
    assert recovered.status_code == 200, recovered.text

    added = client.post(
        "/api/auth/pair",
        json=pairing_payload(identity.pairing_code, device_name="new-device"),
    )
    assert added.status_code == 200, added.text
    assert added.json()["device_public_id"] != target_public_id
    with SessionLocal() as db:
        ordinary_pairing = db.scalar(
            select(PairingCode).where(PairingCode.code_hash == hash_pairing_code(identity.pairing_code))
        )
        assert ordinary_pairing is not None
        assert ordinary_pairing.used_at is not None
        assert ordinary_pairing.revoked_at is None
        assert ordinary_pairing.recovery_device_id is None


def test_pairing_retry_rejects_wrong_attempt_secret(client: TestClient, *, identity) -> None:
    request = pairing_payload(identity.pairing_code)
    paired = client.post("/api/auth/pair", json=request)
    assert paired.status_code == 200, paired.text

    rejected = client.post(
        "/api/auth/pair",
        json={**request, "pairing_attempt_secret": "A" * 43},
    )

    assert rejected.status_code == 401
    assert rejected.json()["error"] == "invalid_pairing_code"


def test_revoked_pairing_result_cannot_be_resurrected(client: TestClient, *, identity) -> None:
    request = pairing_payload(identity.pairing_code)
    paired = client.post("/api/auth/pair", json=request)
    assert paired.status_code == 200, paired.text
    token = paired.json()["session_token"]
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        row.revoked_at = now_utc()
        db.commit()

    rejected = client.post("/api/auth/pair", json=request)

    assert rejected.status_code == 409
    assert rejected.json()["error"] == "pairing_attempt_closed"


def test_expired_pairing_attempt_requires_a_new_code(client: TestClient, *, identity) -> None:
    request = pairing_payload(identity.pairing_code)
    paired = client.post("/api/auth/pair", json=request)
    assert paired.status_code == 200, paired.text
    with SessionLocal() as db:
        attempt = db.scalar(
            select(DeviceEnrollmentAttempt).where(DeviceEnrollmentAttempt.public_id == request["pairing_attempt_id"])
        )
        assert attempt is not None
        attempt.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()

    rejected = client.post("/api/auth/pair", json=request)

    assert rejected.status_code == 409
    assert rejected.json()["error"] == "pairing_attempt_expired"
