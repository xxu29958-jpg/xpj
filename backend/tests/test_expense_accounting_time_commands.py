"""Exercise time semantics at the existing financial command boundaries."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models import Expense, LedgerCalendarRevision
from app.schemas import ExpenseManualCreateRequest, ExpenseUpdateRequest
from app.services import exchange_rate_service
from app.services.expense_accounting_time_service import apply_expense_time_input
from app.services.expense_service import _create, _update_currency


@pytest.fixture
def manual_command(monkeypatch):
    db = Mock(spec=Session)
    db.get.return_value = LedgerCalendarRevision(ledger_id="owner", revision=2, timezone_name="Asia/Shanghai")
    for name in ("resolve_write_capability", "_materialize_category_preference", "sync_expense_tags",
                 "mark_duplicate_status", "record_confirmation_revision"):
        monkeypatch.setattr(_create, name, lambda *_args, **_kwargs: None)
    observed = []
    monkeypatch.setattr(_create, "apply_currency_payload", lambda *_args, **kw: observed.append(
        (kw["expense"].expense_time, kw["expense"].accounting_date)))
    return db, observed


def test_manual_date_only_is_preserved_before_money_and_confirmation(manual_command):
    db, observed = manual_command
    payload = ExpenseManualCreateRequest(client_ref="frozen", home_currency_code="CNY", amount_cents=100,
        category="餐饮", time_input={"precision": "date_only", "calendar_revision": 2,
            "user_local_date": "2026-04-30"})
    expense = _create._insert_manual_expense(db, payload, "owner", draft_idempotency_key="key",
        draft_request_fingerprint="original", actor_account_id=1, actor_device_id=2)
    assert observed == [(None, date(2026, 4, 30))]
    assert expense.confirmed_at is not None
    assert expense.expense_time is None
    assert expense.user_local_date == date(2026, 4, 30)
    assert expense.calendar_revision == 2


def test_exact_instant_and_captured_rule_are_used_before_money(manual_command):
    db, observed = manual_command
    payload = ExpenseManualCreateRequest(client_ref="frozen", home_currency_code="CNY", amount_cents=100,
        category="餐饮", time_input={"precision": "instant", "calendar_revision": 2,
            "user_local_date": "2026-04-30", "instant_utc": "2026-04-30T16:30:00Z",
            "source_timezone": "UTC", "source_utc_offset_seconds": 0})
    expense = _create._insert_manual_expense(db, payload, "owner", draft_idempotency_key="key",
        draft_request_fingerprint="original", actor_account_id=1, actor_device_id=2)
    assert observed == [(datetime(2026, 4, 30, 16, 30, tzinfo=UTC), date(2026, 5, 1))]
    assert expense.user_local_date == date(2026, 4, 30)


def test_date_only_quote_uses_original_day_not_today_or_selected_accounting_period(monkeypatch):
    db = Mock(spec=Session)
    expense = Expense(expense_time=None, time_precision="date_only", user_local_date=date(2026, 4, 30),
        accounting_date=date(2026, 5, 1), home_currency_code="JPY", original_currency_code="USD")
    payload = ExpenseManualCreateRequest(client_ref="date-only", home_currency_code="JPY",
        original_currency="USD", original_amount="2")
    rate_lookup = Mock(return_value=(Decimal("150"), "manual", "ready", date(2026, 4, 30)))
    monkeypatch.setattr(exchange_rate_service, "resolve_write_capability", lambda _db: None)
    monkeypatch.setattr(exchange_rate_service, "resolve_payload_rate", rate_lookup)
    exchange_rate_service.apply_currency_payload(db, tenant_id="owner", home_currency_code="JPY",
        expense=expense, payload=payload, amount_was_explicit=False)
    assert rate_lookup.call_args.kwargs["rate_date"] == date(2026, 4, 30)


def test_changing_only_accounting_day_keeps_frozen_money(monkeypatch):
    db = Mock(spec=Session)
    db.get.return_value = LedgerCalendarRevision(ledger_id="owner", revision=2, timezone_name="UTC")
    expense = Expense(tenant_id="owner", expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        time_precision="instant", user_local_date=date(2026, 4, 30), accounting_date=date(2026, 4, 30),
        calendar_revision=2, home_currency_code="JPY", original_currency_code="USD",
        original_amount_minor=200, amount_cents=300, exchange_rate_to_cny=Decimal("150"), fx_status="ready")
    payload = ExpenseUpdateRequest(expected_row_version=3, time_input={"precision": "instant",
        "calendar_revision": 2, "user_local_date": "2026-04-30", "instant_utc": "2026-04-30T16:30:00Z",
        "source_timezone": "UTC", "accounting_date": "2026-05-01"})
    changed = apply_expense_time_input(db, expense, payload)
    assert changed is False
    monkeypatch.setattr(_update_currency, "apply_currency_payload", lambda *_args, **_kw: pytest.fail("No re-price"))
    _update_currency._apply_update_currency(db, tenant_id="owner", expense=expense, payload=payload,
        updates=payload.model_dump(exclude_unset=True), time_changed=changed)
    assert expense.accounting_date == date(2026, 5, 1)
    assert (expense.amount_cents, expense.exchange_rate_to_cny) == (300, Decimal("150"))


def test_old_null_timestamp_does_not_erase_date_only_evidence():
    db = Mock(spec=Session)
    expense = Expense(tenant_id="owner", expense_time=None, time_precision="date_only",
        user_local_date=date(2026, 4, 30), accounting_date=date(2026, 4, 30), calendar_revision=2)
    assert apply_expense_time_input(db, expense, ExpenseUpdateRequest(expected_row_version=3, expense_time=None)) is False
    db.get.assert_not_called()
    assert expense.time_precision == "date_only" and expense.accounting_date == date(2026, 4, 30)
