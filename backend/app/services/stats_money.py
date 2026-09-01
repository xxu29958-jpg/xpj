"""Checked money projections for statistics and CSV export."""

from collections.abc import Iterable

from app.models import Expense
from app.money_contract import projection_sum_to_int, projection_values_sum_to_int
from app.services.category_service import normalize_category
from app.services.currency_common import minor_amount_value
from app.services.import_money import legacy_yuan_value_from_minor


def export_money_fields(expense: Expense) -> tuple[int | str, str, str]:
    return export_money_values(
        amount_cents=expense.amount_cents,
        home_currency_code=expense.home_currency_code,
        label="stats.export_expense",
    )


def export_money_values(
    *,
    amount_cents: int | None,
    home_currency_code: str,
    label: str,
) -> tuple[int | str, str, str]:
    if amount_cents is None:
        amount_minor: int | str = ""
        legacy_yuan = ""
    else:
        amount_minor = projection_sum_to_int(
            amount_cents,
            label=label,
        )
        legacy_yuan = (
            legacy_yuan_value_from_minor(amount_minor)
            if home_currency_code == "CNY"
            else ""
        )
    home_major = minor_amount_value(
        amount_minor if amount_minor != "" else None,
        home_currency_code,
    )
    return amount_minor, legacy_yuan, home_major


def category_total(
    expenses: Iterable[Expense],
    *,
    category: str,
    label: str,
) -> int:
    return projection_values_sum_to_int(
        (
            expense.amount_cents
            for expense in expenses
            if normalize_category(expense.category) == category
        ),
        label=label,
    )


def merchant_amount_total(current: int, amount_minor: int | None) -> int:
    amount = projection_sum_to_int(
        amount_minor,
        label="stats.merchant_expense",
        empty_is_zero=True,
    )
    return projection_sum_to_int(current + amount, label="stats.merchant_total")


__all__ = [
    "category_total",
    "export_money_fields",
    "export_money_values",
    "merchant_amount_total",
]
