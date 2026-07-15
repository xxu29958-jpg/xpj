from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AuthToken, Device, DeviceEnrollmentAttempt
from app.services.identity_service import hash_secret, pair_device
from app.services.time_service import now_utc
from tests.pairing_test_support import pairing_payload


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
