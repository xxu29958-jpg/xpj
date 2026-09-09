"""Checked money projections for statistics and CSV export."""

from app.money_contract import projection_sum_to_int
from app.services.currency_common import minor_amount_value
from app.services.import_money import legacy_yuan_value_from_minor


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


__all__ = ["export_money_values"]
