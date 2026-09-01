"""Focused pure contracts for recurring-item calculations."""

from __future__ import annotations

from app.models import RecurringItem
from app.services.recurring_service import _historical_average_amount


def test_recurring_history_average_accepts_wide_exact_numerator() -> None:
    item = RecurringItem(
        merchant_key="large-subscription",
        merchant_name="Large subscription",
        frequency="monthly",
        baseline_amount_cents=1,
        last_amount_cents=1,
    )

    assert _historical_average_amount(item, [2**53 - 1] * 1001) == 2**53 - 1
