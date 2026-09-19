"""Exercise time semantics at the existing financial command boundaries."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models import Expense, LedgerCalendarRevision
from app.schemas import ExpenseManualCreateRequest, ExpenseUpdateRequest
from app.services import exchange_rate_service
from app.services.expense_accounting_time_service import apply_expense_time_input, refresh_legacy_expense_time
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


def test_confirm_keeps_imported_agreed_day_when_source_precision_is_unknown():
    db = Mock(spec=Session)
    db.get.return_value = LedgerCalendarRevision(ledger_id="owner", revision=1, timezone_name="UTC")
    expense = Expense(tenant_id="owner", expense_time=None, time_precision="unknown", user_local_date=None,
        accounting_date=date(2026, 4, 30), calendar_revision=1, accounting_date_basis="recorded_date",
        confirmed_at=datetime(2026, 5, 2, tzinfo=UTC))
    refresh_legacy_expense_time(db, expense)
    assert expense.accounting_date == date(2026, 4, 30)
    assert expense.expense_time is None and expense.user_local_date is None
    db.get.assert_not_called()


def _foreign_time_row(*, ready: bool, precision: str = "instant") -> Expense:
    return Expense(tenant_id="owner", status="pending", calendar_revision=2,
        expense_time=datetime(2026, 4, 30, 12, tzinfo=UTC) if precision == "instant" else None,
        time_precision=precision, user_local_date=date(2026, 4, 30), accounting_date=date(2026, 4, 30),
        source_timezone="UTC", source_utc_offset_seconds=0 if precision == "instant" else None,
        home_currency_code="CNY", original_currency_code="USD", original_amount_minor=100,
        amount_cents=700 if ready else None, exchange_rate_to_cny=Decimal("7") if ready else None,
        exchange_rate_date=date(2026, 4, 30), exchange_rate_source="manual" if ready else None,
        fx_status="ready" if ready else "pending")


def _time_edit(*, precision="instant", transaction_day="2026-04-30", **extra):
    time_input = {"precision": precision, "calendar_revision": 2, "user_local_date": transaction_day,
        "source_timezone": "UTC", "accounting_date": "2026-05-01"}
    if precision == "instant":
        time_input["instant_utc"] = f"{transaction_day}T12:00:00Z"
    return ExpenseUpdateRequest(expected_row_version=3, time_input=time_input, **extra)


def _apply_time_and_currency(expense, payload):
    db = Mock(spec=Session)
    db.get.return_value = LedgerCalendarRevision(ledger_id="owner", revision=2, timezone_name="UTC")
    changed = apply_expense_time_input(db, expense, payload)
    _update_currency._apply_update_currency(db, tenant_id="owner", expense=expense, payload=payload,
        updates=payload.model_dump(exclude_unset=True), time_changed=changed)
    return changed


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("precision", ["instant", "date_only"])
@pytest.mark.parametrize("rate_fields", [{}, {"manual_exchange_rate": None}])
def test_accounting_day_only_never_resolves_a_pending_or_ready_quote(monkeypatch, ready, precision, rate_fields):
    expense = _foreign_time_row(ready=ready, precision=precision)
    before = (expense.amount_cents, expense.exchange_rate_to_cny, expense.exchange_rate_date,
        expense.exchange_rate_source, expense.fx_status)
    lookup = Mock(return_value=(Decimal("9"), "manual", "ready", date(2026, 4, 30)))
    monkeypatch.setattr(exchange_rate_service, "resolve_payload_rate", lookup)
    monkeypatch.setattr(exchange_rate_service, "resolve_write_capability", lambda _db: None)

    assert _apply_time_and_currency(expense, _time_edit(precision=precision, **rate_fields)) is False

    lookup.assert_not_called()
    assert expense.accounting_date == date(2026, 5, 1)
    assert (expense.amount_cents, expense.exchange_rate_to_cny, expense.exchange_rate_date,
        expense.exchange_rate_source, expense.fx_status) == before


def test_accounting_day_with_explicit_manual_quote_keeps_quote_recovery(monkeypatch):
    expense = _foreign_time_row(ready=False)
    lookup = Mock()
    monkeypatch.setattr(exchange_rate_service, "resolve_payload_rate", lookup)
    monkeypatch.setattr(exchange_rate_service, "resolve_write_capability", lambda _db: None)

    assert _apply_time_and_currency(expense, _time_edit(manual_exchange_rate="8")) is False

    lookup.assert_not_called()
    assert expense.fx_status == "ready" and expense.amount_cents == 800
    assert expense.exchange_rate_to_cny == Decimal("8")
    assert expense.exchange_rate_date == date(2026, 4, 30)


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("precision", ["instant", "date_only"])
def test_real_transaction_day_edit_still_resolves_new_quote(monkeypatch, ready, precision):
    expense = _foreign_time_row(ready=ready, precision=precision)
    lookup = Mock(return_value=(Decimal("9"), "manual", "ready", date(2026, 5, 2)))
    monkeypatch.setattr(exchange_rate_service, "resolve_payload_rate", lookup)
    monkeypatch.setattr(exchange_rate_service, "resolve_write_capability", lambda _db: None)

    assert _apply_time_and_currency(expense, _time_edit(precision=precision, transaction_day="2026-05-02")) is True

    assert lookup.call_count == 1 and lookup.call_args.kwargs["rate_date"] == date(2026, 5, 2)
    assert expense.fx_status == "ready" and expense.amount_cents == 900
    assert expense.exchange_rate_date == date(2026, 5, 2)
