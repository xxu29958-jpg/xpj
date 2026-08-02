"""C07 amount validation shared by category-rule create and update paths."""

from __future__ import annotations

from app.money_contract import MoneySign, ensure_optional_money_minor


def clean_rule_amount(value: object | None, *, label: str, message: str) -> int | None:
    return ensure_optional_money_minor(
        value,
        sign=MoneySign.NONNEGATIVE,
        label=label,
        error_code="invalid_request",
        error_message=message,
    )


def clean_rule_amount_range(
    amount_min_cents: object | None,
    amount_max_cents: object | None,
) -> tuple[int | None, int | None]:
    return (
        clean_rule_amount(
            amount_min_cents,
            label="category_rule.amount_min_cents",
            message="金额下限不能为负数或超出可支持范围。",
        ),
        clean_rule_amount(
            amount_max_cents,
            label="category_rule.amount_max_cents",
            message="金额上限不能为负数或超出可支持范围。",
        ),
    )


def clean_rule_update_amounts(
    amount_min_cents: object,
    amount_max_cents: object,
    *,
    unset: object,
) -> tuple[object, object]:
    if amount_min_cents is not unset:
        amount_min_cents = clean_rule_amount_range(
            amount_min_cents, None
        )[0]
    if amount_max_cents is not unset:
        amount_max_cents = clean_rule_amount_range(
            None, amount_max_cents
        )[1]
    return amount_min_cents, amount_max_cents
