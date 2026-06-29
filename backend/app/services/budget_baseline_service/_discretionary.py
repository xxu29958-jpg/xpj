"""'本月可自由支配' formula.

    discretionary = income - fixed - spent - savings_target - reserved_buffer

Capped at zero (negative means the user is already underwater on
fixed + actual + planned outflows; v1.1 UI surfaces that as a separate alert).
This module is intentionally pure-arithmetic — no DB reads, no provider
calls — so it can be unit-tested without fixtures and reused from any
service / route / scheduled job that needs the headline number.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscretionaryBreakdown:
    """Inspectable breakdown of the discretionary calculation.

    Returned as a dataclass so the UI can render the subtraction step by
    step ("月收入 X - 固定支出 Y - 已花 Z - 储蓄目标 N = 可自由支配 W")
    without each surface duplicating the maths.
    """

    monthly_income_cents: int
    fixed_expenses_cents: int
    spent_amount_cents: int
    savings_target_cents: int
    reserved_buffer_cents: int
    discretionary_cents: int


def compute_monthly_discretionary(
    *,
    monthly_income_cents: int,
    fixed_expenses_cents: int = 0,
    spent_amount_cents: int = 0,
    savings_target_cents: int = 0,
    reserved_buffer_cents: int = 0,
) -> DiscretionaryBreakdown:
    """Return the 本月可自由支配 amount with its subtractions exposed.

    All inputs are in cents. Negative inputs are accepted (caller may
    have computed them from a partial month) but ``discretionary_cents``
    is floored at zero so downstream UI never has to deal with a
    "negative spendable" oxymoron.
    """
    raw = (
        monthly_income_cents
        - fixed_expenses_cents
        - spent_amount_cents
        - savings_target_cents
        - reserved_buffer_cents
    )
    return DiscretionaryBreakdown(
        monthly_income_cents=monthly_income_cents,
        fixed_expenses_cents=fixed_expenses_cents,
        spent_amount_cents=spent_amount_cents,
        savings_target_cents=savings_target_cents,
        reserved_buffer_cents=reserved_buffer_cents,
        discretionary_cents=max(0, raw),
    )
