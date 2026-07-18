"""End-to-end Web writes that must follow a record's frozen currency."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Account,
    BillSplitInvitation,
    Expense,
    ExpenseItem,
    ExpenseSplit,
    Ledger,
    LedgerMember,
)
from app.services.time_service import now_utc


def _create_pending_frozen_expense(currency_code: str) -> tuple[int, int]:
    now = now_utc()
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=5000,
            home_currency_code=currency_code,
            original_currency_code=currency_code,
            original_amount_minor=5000,
            merchant="冻结币种明细",
            category="其他",
            source="手动记账",
            status="pending",
            expense_time=datetime(2026, 5, 4, 1, 0, tzinfo=UTC),
            created_at=now,
            updated_at=now,
        )
        db.add(expense)
        db.flush()
        member_id = db.scalar(
            select(LedgerMember.id)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member_id is not None
        db.commit()
        return expense.id, member_id


def _write_frozen_currency_item(
    web_client: TestClient,
    *,
    expense_id: int,
) -> int:
    with SessionLocal() as db:
        row_version = db.scalar(select(Expense.row_version).where(Expense.id == expense_id))
    response = web_client.post(
        f"/web/expenses/{expense_id}/items/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(row_version),
            "item_name": ["车票"],
            "item_amount_yuan": ["1234"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    with SessionLocal() as db:
        item_minor = db.scalar(
            select(ExpenseItem.amount_cents)
            .where(ExpenseItem.expense_id == expense_id)
            .where(ExpenseItem.tenant_id == "owner")
        )
        next_row_version = db.scalar(select(Expense.row_version).where(Expense.id == expense_id))
    assert item_minor == 1234
    assert next_row_version is not None
    return next_row_version


def _write_frozen_currency_split(
    web_client: TestClient,
    *,
    expense_id: int,
    member_id: int,
    row_version: int,
) -> None:
    response = web_client.post(
        f"/web/expenses/{expense_id}/splits/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(row_version),
            "split_member_id": [str(member_id)],
            "split_amount_yuan": ["1234"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    with SessionLocal() as db:
        split_minor = db.scalar(
            select(ExpenseSplit.amount_cents)
            .where(ExpenseSplit.expense_id == expense_id)
            .where(ExpenseSplit.tenant_id == "owner")
        )
    assert split_minor == 1234


@pytest.mark.parametrize("currency_code", ["JPY", "KRW"])
def test_web_item_and_split_forms_use_expense_frozen_currency_for_writes(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    currency_code: str,
) -> None:
    # Current server configuration is deliberately CNY. Child records are
    # denominated in the parent expense's frozen home currency.
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        expense_id, member_id = _create_pending_frozen_expense(currency_code)
        next_row_version = _write_frozen_currency_item(
            web_client,
            expense_id=expense_id,
        )
        _write_frozen_currency_split(
            web_client,
            expense_id=expense_id,
            member_id=member_id,
            row_version=next_row_version,
        )

        page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
        assert page.status_code == 200
        assert page.context["home_currency_input"]["currency_code"] == "CNY"
        frozen_input = page.context["expense_currency_input"]
        assert frozen_input["currency_code"] == currency_code
        assert frozen_input["minor_unit_digits"] == 0
        assert frozen_input["amount_step"] == "1"
        assert page.context["receipt_items"]["rows"][0]["amount_yuan"] == "1234"
        assert page.context["split_rows"]["rows"][0]["amount_yuan"] == "1234"
    finally:
        get_settings.cache_clear()


def _create_confirmed_split_source(currency_code: str) -> tuple[int, int]:
    now = now_utc()
    with SessionLocal() as db:
        receiver = Account(display_name=f"{currency_code} receiver")
        db.add(receiver)
        db.flush()
        receiver_ledger = Ledger(
            ledger_id=f"receiver_{currency_code.lower()}",
            name=f"{currency_code} 接收账本",
            owner_account_id=receiver.id,
        )
        db.add(receiver_ledger)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id=receiver_ledger.ledger_id,
                account_id=receiver.id,
                role="owner",
            )
        )
        expense = Expense(
            tenant_id="owner",
            amount_cents=5000,
            home_currency_code=currency_code,
            original_currency_code=currency_code,
            original_amount_minor=5000,
            merchant="冻结币种拆账",
            category="其他",
            source="手动记账",
            status="confirmed",
            expense_time=now,
            confirmed_at=now,
        )
        db.add(expense)
        db.commit()
        return receiver.id, expense.id


@pytest.mark.parametrize(
    ("currency_code", "expected_label"),
    [
        pytest.param("JPY", "¥1,200", id="jpy-frozen-invitation"),
        pytest.param("KRW", "₩1,200", id="krw-frozen-invitation"),
    ],
)
def test_web_bill_split_invite_uses_expense_frozen_currency_for_write_and_display(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    currency_code: str,
    expected_label: str,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        receiver_account_id, expense_id = _create_confirmed_split_source(currency_code)
        created = web_client.post(
            f"/web/expenses/{expense_id}/split-invite",
            data={
                "ledger_id": "owner",
                "receiver_account_id": str(receiver_account_id),
                "amount_yuan": "1200",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, created.text
        with SessionLocal() as db:
            invitation = db.scalar(
                select(BillSplitInvitation).where(BillSplitInvitation.sender_expense_id == expense_id)
            )
            assert invitation is not None
            assert invitation.amount_cents == 1200
            assert invitation.home_currency_code == currency_code
            invitation_public_id = invitation.public_id

        sent = web_client.get("/web/bill-splits/sent?ledger_id=owner")
        assert sent.status_code == 200
        row = next(item for item in sent.context["bill_split_rows"] if item["public_id"] == invitation_public_id)
        assert row["amount_value"] == "1200"
        assert row["amount_label"] == expected_label
    finally:
        get_settings.cache_clear()
