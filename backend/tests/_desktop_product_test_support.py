"""Shared request and fixture helpers for Desktop product backend tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthToken, Device, Expense
from app.services.identity_service import hash_secret, new_session_token
from app.services.time_service import now_utc

BRIDGE_HEADERS = {"X-Ticketbox-Desktop-Bridge": "v1"}
WORKSPACES = ("inbox", "transactions", "obligations", "plans", "insights")


def mint_desktop_token_from(source_token_value: str) -> str:
    """Mint a distinct Desktop credential for an existing test principal."""
    token_value = new_session_token()
    with SessionLocal() as db:
        source = db.scalar(
            select(AuthToken)
            .where(AuthToken.token_hash == hash_secret(source_token_value))
            .limit(1)
        )
        assert source is not None
        device = Device(
            account_id=source.account_id,
            device_name=f"pytest-desktop-{uuid4()}",
            platform="desktop",
        )
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(token_value),
                account_id=source.account_id,
                device_id=device.id,
                ledger_id=source.ledger_id,
                scope="app",
            )
        )
        db.commit()
    return token_value


def seed_expenses(*, tenant_id: str = "owner") -> tuple[str, str]:
    now = now_utc()
    pending_id = str(uuid4())
    confirmed_id = str(uuid4())
    with SessionLocal() as db:
        db.add_all(
            [
                Expense(
                    tenant_id=tenant_id,
                    public_id=pending_id,
                    amount_cents=1880,
                    merchant="真实收件商家",
                    category="餐饮",
                    source="pytest-desktop",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                ),
                Expense(
                    tenant_id=tenant_id,
                    public_id=confirmed_id,
                    amount_cents=2600,
                    merchant="真实流水商家",
                    category="交通",
                    source="pytest-desktop",
                    status="confirmed",
                    created_at=now,
                    updated_at=now,
                    confirmed_at=now,
                ),
            ]
        )
        db.commit()
    return pending_id, confirmed_id


def allow_testclient_loopback(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.desktop_product.require_owner_console_local",
        lambda _request: None,
    )


def principal_headers(token: str) -> dict[str, str]:
    return {
        **BRIDGE_HEADERS,
        "Authorization": f"Bearer {token}",
    }


def workspace(
    client: TestClient,
    workspace_name: str,
    *,
    token: str,
    ledger_id: str | None = None,
):
    suffix = f"?ledger_id={ledger_id}" if ledger_id else ""
    return client.get(
        f"/desktop/workspaces/{workspace_name}{suffix}",
        headers=principal_headers(token),
    )


def command(
    client: TestClient,
    public_id: str,
    *,
    body: dict,
    key: str | None,
    token: str,
    ledger_id: str | None = None,
):
    suffix = f"?ledger_id={ledger_id}" if ledger_id else ""
    headers = principal_headers(token)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        f"/desktop/workspaces/inbox/expenses/{public_id}/commands{suffix}",
        headers=headers,
        json=body,
    )
