"""Additional bill split contract hardening tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, Ledger, LedgerMember
from app.services import bill_split_service as bsplit
from app.services.time_service import now_utc
from tests.test_bill_split import (
    _make_expense_for_owner,
    _owner_account_id,
    _seed_receiver,
)


def test_active_split_invitation_total_cannot_exceed_parent_expense(
    client: TestClient, *, identity
) -> None:
    expense_id = _make_expense_for_owner(amount_cents=5000)
    receiver_a = _seed_receiver(name="B-cap-a", ledger_id="receiver_cap_a")
    receiver_b = _seed_receiver(name="B-cap-b", ledger_id="receiver_cap_b")

    first = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_a, "amount_cents": 3000},
    )
    assert first.status_code == 200, first.json()

    second = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_b, "amount_cents": 2500},
    )
    assert second.status_code == 422
    assert second.json()["error"] == "split_total_exceeds_parent"


def test_create_invitation_requires_own_transaction_for_total_guard() -> None:
    expense_id = _make_expense_for_owner(amount_cents=5000)
    receiver_account_id = _seed_receiver(
        name="B-guard",
        ledger_id="receiver_guard",
    )
    sender_account_id = _owner_account_id()

    with SessionLocal() as db, pytest.raises(AppError) as exc_info:
        db.scalar(select(Expense.id).limit(1))
        bsplit.create_invitation(
            db,
            sender_account_id=sender_account_id,
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
        )

    assert exc_info.value.error == "state_conflict"
    assert exc_info.value.status_code == 409


def test_reaccept_with_different_target_ledger_is_conflict() -> None:
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(
        name="B-idem-target",
        ledger_id="receiver_idem_target_a",
    )
    with SessionLocal() as db:
        db.add(
            Ledger(
                ledger_id="receiver_idem_target_b",
                name="B-idem-target backup ledger",
                owner_account_id=receiver_account_id,
            )
        )
        db.add(
            LedgerMember(
                ledger_id="receiver_idem_target_b",
                account_id=receiver_account_id,
                role="owner",
            )
        )
        db.commit()

    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
        )
        public_id = inv.public_id
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_idem_target_a",
        )

    with SessionLocal() as db, pytest.raises(AppError) as exc_info:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_idem_target_b",
        )
    assert exc_info.value.error == "state_conflict"
    assert exc_info.value.status_code == 409


def test_bill_split_copies_exchange_rate_date_to_received_expense() -> None:
    rate_date = date(2026, 5, 1)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=7000,
            home_currency_code="CNY",
            original_currency_code="USD",
            original_amount_minor=1000,
            exchange_rate_to_cny=Decimal("7.00000000"),
            exchange_rate_date=rate_date,
            exchange_rate_source="manual",
            merchant="Foreign Cafe",
            category="food",
            source="iphone_screenshot",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id

    receiver_account_id = _seed_receiver(
        name="B-fx",
        ledger_id="receiver_fx_snapshot",
    )

    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=3500,
        )
        assert inv.exchange_rate_date is not None
        assert inv.exchange_rate_date.date() == rate_date
        _inv, received = bsplit.accept_invitation(
            db,
            public_id=inv.public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_fx_snapshot",
        )
        received_id = received.id

    with SessionLocal() as db:
        received = db.scalar(
            select(Expense)
            .where(Expense.id == received_id)
            .where(Expense.tenant_id == "receiver_fx_snapshot")
        )
        assert received is not None
        assert received.exchange_rate_date == rate_date
