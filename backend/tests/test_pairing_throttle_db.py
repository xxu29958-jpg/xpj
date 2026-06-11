"""v1.1 Batch 1: pairing-attempt throttle persisted in DB.

Module previously held failures in a per-process dict; v1.1 moves them
into the ``pairing_attempt_failures`` table so the limit survives a
restart and applies across workers.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PairingAttemptFailure
from app.services.identity_service._models import PAIRING_MAX_FAILED_ATTEMPTS


def _pair(client: TestClient, *, code: str, device_name: str = "pytest-throttle"):
    return client.post(
        "/api/auth/pair",
        json={
            "pairing_code": code,
            "device_name": device_name,
            "platform": "android",
        },
    )


def test_failed_pair_attempt_persists_to_db(client: TestClient, *, identity) -> None:
    response = _pair(client, code="DEFINITELY-WRONG-CODE")
    assert response.status_code == 401
    with SessionLocal() as db:
        rows = db.execute(select(PairingAttemptFailure)).scalars().all()
        assert len(rows) == 1
        assert rows[0].remote_key.startswith("peer:")


def test_throttle_returns_429_after_max_attempts(
    client: TestClient, *, identity,
) -> None:
    for _ in range(PAIRING_MAX_FAILED_ATTEMPTS):
        _pair(client, code="DEFINITELY-WRONG-CODE")
    response = _pair(client, code="DEFINITELY-WRONG-CODE")
    assert response.status_code == 429
    # §4 generic throttle code — NOT invalid_pairing_code: the client copy for
    # that code ("绑定码无效，请重新获取") sends the user into a retry loop the
    # throttle exists to stop. Copy is pinned here because the three-surface
    # lane only reconciles strings.xml/doc against each other for repo-arm codes.
    assert response.json()["error"] == "rate_limited"
    assert response.json()["message"] == "尝试太频繁，请稍后再试。"


def test_successful_pair_clears_throttle_rows(
    client: TestClient, *, identity,
) -> None:
    _pair(client, code="WRONG-CODE")
    with SessionLocal() as db:
        before = db.scalar(select(PairingAttemptFailure).limit(1))
        assert before is not None

    response = _pair(client, code=identity.pairing_code)
    assert response.status_code == 200

    with SessionLocal() as db:
        remaining = db.execute(select(PairingAttemptFailure)).scalars().all()
        # Only failure rows for this remote_key should be cleared; we
        # had exactly one, so the table is now empty.
        assert remaining == []
