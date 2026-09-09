"""Refreshing a saved money fact cannot reinterpret it in today's default."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, InstallationCurrencyBinding
from app.runtime_compatibility_contract import RUNTIME_COMPATIBILITY_SESSION_KEY, RuntimeCompatibilityRequest
from app.schemas import ExpenseUpdateRequest
from app.services import exchange_rate_service
from app.services.expense_service._update_currency import _apply_update_currency
from app.services.import_service import parse_csv_preview


def _current_cny_session() -> Session:
    db = Mock(spec=Session)
    db.info = {}
    db.scalar.return_value = InstallationCurrencyBinding(
        singleton_id=1, state="ACTIVE", home_currency_code="CNY", binding_revision=1,
        currency_contract_version=1, minor_unit_exponent=2, rounding_mode="ROUND_HALF_UP",
    )
    return db


def _jpy_expense() -> Expense:
    return Expense(tenant_id="owner", home_currency_code="JPY", original_currency_code="USD",
        original_amount_minor=100, amount_cents=None, fx_status="pending", status="pending",
        expense_time=datetime(2026, 9, 8, 2, tzinfo=UTC), exchange_rate_date=date(2026, 9, 8))


def _rates(monkeypatch) -> Mock:
    lookup = Mock(side_effect=lambda _db, **kw: (
        Decimal("150") if kw["home_currency_code"] == "JPY" else Decimal("7"),
        "manual", "ready", kw["rate_date"],
    ))
    monkeypatch.setattr(exchange_rate_service, "resolve_payload_rate", lookup)
    return lookup


def test_pending_fx_refresh_preserves_the_saved_currency_under_another_current_default(monkeypatch):
    lookup = _rates(monkeypatch)
    expense = _jpy_expense()
    exchange_rate_service.refresh_currency_snapshot(_current_cny_session(), tenant_id="owner", expense=expense)
    assert expense.home_currency_code == "JPY"
    assert expense.amount_cents == 150
    assert expense.original_currency_code == "USD"
    assert expense.original_amount_minor == 100
    assert expense.exchange_rate_to_cny == Decimal("150")
    assert lookup.call_args.kwargs["home_currency_code"] == "JPY"


def test_changing_a_saved_expense_date_resolves_fx_again_in_that_records_currency(monkeypatch):
    lookup = _rates(monkeypatch)
    expense = _jpy_expense()
    changed_time = datetime(2026, 9, 9, 2, tzinfo=UTC)
    payload = ExpenseUpdateRequest(expected_row_version=1, spent_at=changed_time)
    _apply_update_currency(_current_cny_session(), tenant_id="owner", expense=expense,
                          payload=payload, updates={"spent_at": changed_time})
    assert expense.home_currency_code == "JPY"
    assert expense.amount_cents == 150
    assert expense.exchange_rate_date == date(2026, 9, 9)
    assert lookup.call_args.kwargs["home_currency_code"] == "JPY"


def test_new_native_amount_uses_the_explicit_intent_currency():
    expense = Expense(tenant_id="owner")
    exchange_rate_service.apply_currency_payload(_current_cny_session(), tenant_id="owner",
        home_currency_code="JPY", expense=expense, payload=SimpleNamespace(amount_cents=1200),
        amount_was_explicit=True)
    assert expense.home_currency_code == "JPY"
    assert expense.original_currency_code == "JPY"
    assert expense.amount_cents == expense.original_amount_minor == 1200


def test_frozen_amount_correction_keeps_recorded_home_and_rate_after_default_change(monkeypatch):
    lookup = _rates(monkeypatch)
    expense = _jpy_expense()
    expense.status, expense.fx_status = "confirmed", "ready"
    expense.amount_cents, expense.exchange_rate_to_cny = 150, Decimal("150")
    payload = ExpenseUpdateRequest(expected_row_version=1, original_amount_minor=200)

    _apply_update_currency(_current_cny_session(), tenant_id="owner", expense=expense,
        payload=payload, updates={"original_amount_minor": 200})

    assert (expense.home_currency_code, expense.original_currency_code, expense.original_amount_minor,
        expense.amount_cents, expense.exchange_rate_to_cny) == ("JPY", "USD", 200, 300, Decimal("150"))
    lookup.assert_not_called()


def test_frozen_amount_correction_still_refuses_unversioned_money_writes():
    db = _current_cny_session()
    db.info[RUNTIME_COMPATIBILITY_SESSION_KEY] = RuntimeCompatibilityRequest(None, None)
    expense = _jpy_expense()
    expense.status, expense.fx_status = "confirmed", "ready"
    expense.amount_cents, expense.exchange_rate_to_cny = 150, Decimal("150")
    payload = ExpenseUpdateRequest(expected_row_version=1, original_amount_minor=200)
    with pytest.raises(AppError) as failure:
        _apply_update_currency(db, tenant_id="owner", expense=expense,
            payload=payload, updates={"original_amount_minor": 200})
    assert failure.value.error == "client_upgrade_required"
    assert (expense.original_amount_minor, expense.amount_cents) == (100, 150)


def test_a_parsed_import_retains_the_currency_used_to_read_its_minor_units():
    preview = parse_csv_preview("home_currency_code,amount_cents,merchant\nJPY,1200,Train\n", home_currency="JPY")
    row = preview.rows[0]
    assert row.is_valid, row.error
    assert row.home_currency_code == row.original_currency_code == "JPY"
    assert row.amount_cents == row.original_amount_minor == 1200
