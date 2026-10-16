"""Shared helpers for the desktop two-phase credential test modules."""

from __future__ import annotations

import secrets as secrets_module
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.middleware.web_session import DESKTOP_BRIDGE_HEADER, DESKTOP_BRIDGE_VERSION
from app.models import Account, AuthToken, DesktopActivationAttempt, Device, Ledger, LedgerMember
from app.services.identity_service import new_session_token
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
    payload, _ = pair_desktop(client, pairing_code)
    response = activate(client, payload)
    assert response.status_code == 200, response.text
    token = response.json()["session_token"]
    return payload, {"Authorization": f"Bearer {token}"}


def _create_ledger(client: TestClient, headers: dict[str, str], name: str = "桌面第二账本") -> str:
    response = client.post("/api/ledgers", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["ledger_id"])


LOOPBACK_BASE_URL = "http://127.0.0.1:8000"


REVOKE_PATH = "/desktop/session/revoke"


def _bridge_headers(token: str, *, marker: str = DESKTOP_BRIDGE_VERSION) -> dict[str, str]:
    return {
        DESKTOP_BRIDGE_HEADER: marker,
        "Authorization": f"Bearer {token}",
    }


LOOPBACK_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class _Principal:
    token: str
    account_id: int
    device_id: int
    ledger_id: str


def _principal_headers(
    token: str | None,
    *,
    marker: str = DESKTOP_BRIDGE_VERSION,
) -> dict[str, str]:
    headers = {DESKTOP_BRIDGE_HEADER: marker}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mint_principal(
    *,
    ledger_id: str = "owner",
    role: str = "owner",
    platform: str = "desktop",
    scope: str = "app",
    expires_at: datetime | None = None,
) -> _Principal:
    token = new_session_token()
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id))
        assert ledger is not None
        if role == "owner":
            membership = db.scalar(
                select(LedgerMember)
                .where(LedgerMember.ledger_id == ledger_id)
                .where(LedgerMember.role == "owner")
                .where(LedgerMember.disabled_at.is_(None))
                .limit(1)
            )
            assert membership is not None
            account_id = membership.account_id
        else:
            account = Account(display_name=f"bridge-{role}-{uuid4()}")
            db.add(account)
            db.flush()
            account_id = account.id
            db.add(
                LedgerMember(
                    ledger_id=ledger_id,
                    account_id=account_id,
                    role=role,
                )
            )

        device = Device(
            account_id=account_id,
            device_name=f"pytest-{platform}-bridge",
            platform=platform,
        )
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account_id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope=scope,
                expires_at=expires_at,
            )
        )
        db.commit()
        return _Principal(
            token=token,
            account_id=account_id,
            device_id=device.id,
            ledger_id=ledger_id,
        )
