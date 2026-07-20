"""Form-layer exact-precision parsing for major-unit amount inputs.

Over-precision user input must be rejected, never silently rounded —
independent of which web form collects it.
"""

from __future__ import annotations

import pytest

from app.errors import AppError
from app.routes._web_expense_helpers import parse_amount_yuan
from app.routes.web_budgets import _parse_amount_yuan as _budget_amount
from app.routes.web_goals import _parse_amount_yuan as _goal_amount


def test_helpers_parse_amount_yuan_accepts_two_fraction_digits() -> None:
    assert parse_amount_yuan("12.34") == (1234, None)
    assert parse_amount_yuan("0.01") == (1, None)
    assert parse_amount_yuan("") == (None, None)


def test_helpers_parse_amount_yuan_rejects_over_precision() -> None:
    value, error = parse_amount_yuan("12.345")
    assert value is None
    assert error is not None and "最多填写 2 位小数" in error


def test_helpers_parse_amount_yuan_rejects_invalid_and_negative() -> None:
    assert parse_amount_yuan("abc")[1] is not None
    assert parse_amount_yuan("-1.00")[1] == "金额不能为负数。"


def test_budgets_parser_accepts_exact_amount() -> None:
    assert _budget_amount("100.50", label="月度总预算") == 10050


def test_budgets_parser_rejects_over_precision() -> None:
    with pytest.raises(AppError) as exc_info:
        _budget_amount("0.001", label="月度总预算")
    assert exc_info.value.status_code == 422
    assert "最多填写 2 位小数" in str(exc_info.value)


def test_budgets_parser_allow_negative() -> None:
    assert _budget_amount("-5.25", label="结转金额", allow_negative=True) == -525
    with pytest.raises(AppError):
        _budget_amount("-5.25", label="结转金额")


def test_goals_parser_accepts_exact_amount() -> None:
    assert _goal_amount("2000") == 200000


def test_goals_parser_rejects_over_precision_and_non_positive() -> None:
    with pytest.raises(AppError) as exc_info:
        _goal_amount("0.005")
    assert "最多填写 2 位小数" in str(exc_info.value)
    with pytest.raises(AppError):
        _goal_amount("0")
