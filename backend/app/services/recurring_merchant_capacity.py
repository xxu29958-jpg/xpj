"""Storage-shape guard shared by every RecurringItem writer."""

from __future__ import annotations

from app.errors import AppError

RECURRING_MERCHANT_MAX_LENGTH = 255


def ensure_recurring_merchant_storage_shape(*, merchant_name: str, merchant_key: str) -> None:
    """Reject display or normalized identity that cannot fit the owned fact."""
    if (
        len(merchant_name) > RECURRING_MERCHANT_MAX_LENGTH
        or len(merchant_key) > RECURRING_MERCHANT_MAX_LENGTH
    ):
        raise AppError("recurring_merchant_too_long", status_code=422)
