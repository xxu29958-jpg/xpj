"""Money command validation for income plans."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

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


def project_income_amount(
    db: Session, *, tenant_id: str, amount_minor: int, source_currency: str, home_currency: str, rate_date: date,
) -> int | None:
    """Read-only reporting conversion; the plan and its revision remain unchanged."""
    from app.services.exchange_rate_service import calculate_cny_cents, resolve_payload_rate

    rate, _, _, _ = resolve_payload_rate(
        db, tenant_id=tenant_id, currency_code=source_currency,
        home_currency_code=home_currency, rate_date=rate_date,
    )
    return calculate_cny_cents(
        home_currency_code=home_currency, original_currency_code=source_currency,
        original_amount_minor=amount_minor, exchange_rate_to_cny=rate,
    )


__all__ = [
    "project_income_amount",
    "updated_income_amount_cents",
    "validate_income_plan_amount",
]
