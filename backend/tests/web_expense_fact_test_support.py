"""Shared real-HTTP setup for Web confirmed-expense fact tests."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember


def create_confirmed(client: TestClient, *, identity, merchant: str = "测试商家") -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def row_version(client: TestClient, expense_id: int, identity) -> int:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.text
    return int(snapshot.json()["row_version"])


def owner_member_id() -> int:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member is not None
        return member.id
