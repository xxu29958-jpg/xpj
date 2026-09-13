"""Missing FX carries the attempted fact's exact basis into recovery consumers."""

from datetime import date

import pytest

from app.errors import AppError
from app.models import Expense
from app.routes._web_correction_command import _command_error
from app.services.expense_service._helpers import _ensure_expense_can_confirm


def test_missing_rate_exposes_recorded_pair_and_effective_date():
    expense = Expense(home_currency_code="JPY", original_currency_code="USD",
        original_amount_minor=200, amount_cents=None, fx_status="pending",
        exchange_rate_date=date(2026, 5, 4))
    with pytest.raises(AppError) as raised:
        _ensure_expense_can_confirm(expense)
    error = raised.value
    assert error.error == "exchange_rate_pending" and error.status_code == 409
    assert error.details == {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-05-04"}
    assert _command_error(error).error_details == error.details


def test_unknown_fact_basis_is_not_filled_from_today_or_installation_default():
    expense = Expense(original_amount_minor=200, amount_cents=None, fx_status="pending")
    with pytest.raises(AppError) as raised:
        _ensure_expense_can_confirm(expense)
    assert raised.value.details == {"currency_code": None, "home_currency_code": None, "rate_date": None}


def test_ready_fact_and_amount_error_keep_their_original_contract():
    _ensure_expense_can_confirm(Expense(amount_cents=150, fx_status="ready"))
    with pytest.raises(AppError, match="请先填写金额") as raised:
        _ensure_expense_can_confirm(Expense(amount_cents=None, fx_status="ready"))
    assert raised.value.error == "amount_required"
    assert raised.value.details is None
