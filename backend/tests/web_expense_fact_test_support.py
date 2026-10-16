"""Shared real-HTTP setup for Web confirmed-expense fact tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.middleware import csrf
from app.models import Account, AuthToken, Device, Expense, ExpenseItem, ExpenseSplit, LedgerAuditLog, LedgerMember
from app.routes import expenses, web_expense_edit, web_expense_lifecycle
from app.schemas import ExpenseAcknowledgeItemsMismatchRequest, ExpenseItemReplaceRequest, ExpenseSplitReplaceRequest
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.tenants import AuthContext


def create_confirmed(client: TestClient, *, identity, merchant: str = "测试商家") -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": 1234,
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


def confirmation_actor(db) -> AuthContext:
    account = db.scalar(select(Account).join(LedgerMember).where(LedgerMember.ledger_id == "owner"))
    assert account is not None
    device = db.scalar(select(Device).where(Device.account_id == account.id, Device.device_name == "pytest-android"))
    assert device is not None
    token = db.scalar(select(AuthToken).where(AuthToken.device_id == device.id, AuthToken.ledger_id == "owner"))
    assert token is not None
    return AuthContext(account.id, account.public_id, account.display_name, "owner", "家庭账本",
        device.id, device.public_id, device.device_name, "owner", "app", token.id, token.token_hash)


@pytest.fixture
def confirmation_store(identity):
    """One valid pending fact and actor; every consumer uses the real session factory."""
    now = datetime(2026, 10, 8, tzinfo=UTC)
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(id=42, public_id="original-expense", tenant_id="owner", merchant="首次便利店", category="购物",
            home_currency_code="CNY", original_currency_code="JPY", original_amount_minor=2850, amount_cents=12860,
            exchange_rate_to_cny=Decimal("0.045123"), exchange_rate_source="manual", exchange_rate_date=now,
            source="上传", status="pending", fx_status="ready", duplicate_status="none", row_version=4,
            fact_revision=0, created_at=now, updated_at=now, expense_time=now)
        refresh_legacy_expense_time(db, expense)
        db.add(expense)
        db.commit()
    return SessionLocal


@pytest.fixture
def confirmation_web(confirmation_store, monkeypatch):
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"confirmation-page-test-only")
    options = [SimpleNamespace(ledger_id="owner", name="家庭账本", role="owner", is_default=True)]
    monkeypatch.setattr(web_expense_lifecycle, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_expense_lifecycle, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_expense_lifecycle, "resolve_web_actor", lambda *args: (None, None))
    monkeypatch.setattr(web_expense_edit, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_expense_edit, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_expense_edit, "resolve_web_actor", lambda *args: (None, None))
    app = FastAPI()
    app.include_router(web_expense_lifecycle.router)
    app.include_router(web_expense_edit.router)
    app.dependency_overrides[web_expense_lifecycle.LocalOnly.dependency] = lambda: None

    def database():
        with confirmation_store() as db:
            yield db

    app.dependency_overrides[web_expense_lifecycle.get_db] = database
    return TestClient(app), options


def _submit(db, kind, version, key, *, label="原输入", amount=500):
    auth = confirmation_actor(db)
    if kind == "items":
        route = expenses.put_expense_item_rows
        payload = ExpenseItemReplaceRequest(expected_row_version=version,
            items=[{"name": label, "amount_cents": amount, "category": "购物"}])
    elif kind == "splits":
        route = expenses.put_expense_split_rows
        payload = ExpenseSplitReplaceRequest(expected_row_version=version,
            splits=[{"member_id": db.scalar(select(LedgerMember.id).where(
                LedgerMember.ledger_id == "owner", LedgerMember.account_id == auth.account_id)),
                "amount_cents": amount, "note": label}])
    else:
        route = expenses.acknowledge_expense_items_mismatch
        payload = ExpenseAcknowledgeItemsMismatchRequest(expected_row_version=version)
    return route("42", payload, idempotency_key=key, auth=auth, db=db)


def _prepare(db, kind):
    if kind == "ack":
        return _submit(db, "items", 4, "seed-mismatch").row_version
    return 4


def _facts(db):
    expense = db.get(Expense, 42)
    return (expense.status, expense.row_version, expense.amount_cents, expense.items_sum_status,
        [(row.name, row.amount_cents) for row in db.scalars(select(ExpenseItem))],
        [(row.member_id, row.amount_cents, row.note) for row in db.scalars(select(ExpenseSplit))],
        [(row.action, row.actor_account_id) for row in db.scalars(select(LedgerAuditLog))])
