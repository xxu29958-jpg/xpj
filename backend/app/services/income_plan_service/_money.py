"""Money command validation for income plans."""

from __future__ import annotations

from app.models import MonthlyIncomePlan
from app.money_contract import MoneySign, ensure_money_minor


def validate_income_plan_amount(value: object) -> int:
    return ensure_money_minor(
        value,
        sign=MoneySign.NONNEGATIVE,
        label="income_plan.amount_cents",
        error_code="invalid_request",
        error_message="金额不能为负数或超出可支持范围。",
    )


def updated_income_amount_cents(
    plan: MonthlyIncomePlan,
    amount_cents: object | None,
) -> int:
    if amount_cents is None:
        return plan.amount_cents
    return validate_income_plan_amount(amount_cents)


__all__ = [
    "updated_income_amount_cents",
    "validate_income_plan_amount",
]
