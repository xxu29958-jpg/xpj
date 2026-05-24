"""Field-immutability guard for received splits (called from update_expense)."""

from __future__ import annotations

from app.errors import AppError
from app.models import Expense
from app.services.bill_split_service._common import SPLIT_RECEIVED_SOURCE

#: Fields in :class:`Expense` that cannot be modified once the row is a
#: received split (would silently mutate the agreed-upon debt). Updates
#: against any of these on a ``source='bill_split_received'`` expense
#: must raise ``split_received_field_immutable``.
IMMUTABLE_ON_SPLIT_RECEIVED: frozenset[str] = frozenset({
    "amount_cents",
    "original_currency",
    "original_currency_code",
    "original_amount",
    "original_amount_minor",
    "exchange_rate_to_cny",
    "exchange_rate_date",
    "exchange_rate_source",
    "expense_time",
    "spent_at",
    "merchant",
})


def assert_no_immutable_field_changes(
    expense: Expense, changed_fields: set[str]
) -> None:
    """Service-layer guard called by :func:`update_expense`."""
    if expense.source != SPLIT_RECEIVED_SOURCE:
        return
    forbidden = changed_fields & IMMUTABLE_ON_SPLIT_RECEIVED
    if forbidden:
        names = "、".join(sorted(forbidden))
        raise AppError(
            "split_received_field_immutable",
            f"已接受的拆账中以下字段不能修改：{names}。",
            status_code=400,
        )
