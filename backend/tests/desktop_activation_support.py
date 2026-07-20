"""Shared helpers for the desktop two-phase credential test modules."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthToken, DesktopActivationAttempt
from app.services.session_lifecycle_service import hash_secret
from tests.pairing_test_support import pairing_payload


def pair_desktop(client: TestClient, pairing_code: str, **overrides) -> tuple[dict, dict]:
    payload = pairing_payload(pairing_code, device_name="pytest-desktop", platform="desktop", **overrides)
    response = client.post("/api/auth/pair", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


def activate(client: TestClient, payload: dict, *, previous: str | None = None):
    body = {
        "activation_attempt_id": payload["pairing_attempt_id"],
        "activation_attempt_secret": payload["pairing_attempt_secret"],
    }
    headers = {"X-Ticketbox-Previous-Session": previous} if previous else None
    return client.post("/api/auth/desktop/activate", json=body, headers=headers)


def token_row(token_value: str) -> AuthToken:
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value)))
        assert row is not None
        db.expunge(row)
        return row


def attempt_row(public_id: str) -> DesktopActivationAttempt:
    with SessionLocal() as db:
        row = db.scalar(select(DesktopActivationAttempt).where(DesktopActivationAttempt.public_id == public_id))
        assert row is not None
        db.expunge(row)
        return row


def live_tokens(device_id: int, scope: str) -> list[AuthToken]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuthToken)
            .where(AuthToken.device_id == device_id)
            .where(AuthToken.scope == scope)
            .where(AuthToken.revoked_at.is_(None))
        ).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def new_desktop_pairing_code(client: TestClient, headers: dict[str, str], ledger_id: str = "owner") -> str:
    response = client.post(
        f"/api/ledgers/{ledger_id}/devices/pairing-codes",
        headers=headers,
        json={},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["pairing_code"])
