"""Amount validation and captured-currency continuity for category-rule writes."""

from __future__ import annotations

from typing import Any, cast

from app.errors import AppError
from app.money_contract import MoneySign, ensure_optional_money_minor
from app.services.currency_common import normalize_currency_code


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
    lower, upper = (
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
    if lower is not None and upper is not None and lower > upper:
        raise AppError("invalid_request", "金额下限不能大于上限。", status_code=422)
    return lower, upper


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


def rule_money_update_values(
    *, existing_min: int | None, existing_max: int | None, saved_currency: str | None,
    amount_min_cents: object, amount_max_cents: object, home_currency_code: object, unset: object,
) -> dict[str, Any]:
    """Produce only supplied money changes; preserve omitted bounds and captured units."""
    values: dict[str, Any] = {}
    changing_amounts = amount_min_cents is not unset or amount_max_cents is not unset
    next_min = existing_min if amount_min_cents is unset else cast(int | None, amount_min_cents)
    next_max = existing_max if amount_max_cents is unset else cast(int | None, amount_max_cents)
    if changing_amounts:
        values["amount_min_cents"], values["amount_max_cents"] = clean_rule_amount_range(next_min, next_max)
    required = changing_amounts and any((saved_currency is not None, next_min is not None, next_max is not None))
    submitted_currency = _validated_update_currency(saved_currency, home_currency_code, unset=unset,
        required=required, legacy_amounts=existing_min is not None or existing_max is not None)
    if saved_currency is None and submitted_currency is not None:
        values["home_currency_code"] = submitted_currency
    return values


def _validated_update_currency(
    saved: str | None, submitted: object, *, unset: object, required: bool, legacy_amounts: bool,
) -> str | None:
    currency = normalize_currency_code(cast(str, submitted)) if submitted is not unset and submitted is not None else None
    if saved is not None and submitted is not unset and currency != saved:
        raise AppError("rule_currency_mismatch", "请按规则已保存的币种编辑金额条件。", status_code=409)
    if required and currency is None:
        raise AppError("rule_currency_required", "请明确金额条件的币种。", status_code=422)
    if saved is None and legacy_amounts:
        raise AppError("rule_currency_requires_adoption", "请先核对原金额条件的币种。", status_code=409)
    return currency
