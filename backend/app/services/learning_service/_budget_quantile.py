"""v1.2 P2 — budget quantile suggestion (P50 / P75).

Looks at the user's confirmed-expense history per category and returns
distribution-based budget hints: P50 ("typical month") and P75 ("a
heavier month — leave headroom"). The suggestion is suggestion-only,
exactly like its P1 cousins: never writes a budget, never modifies
existing budgets. The user accepts it via the existing budget
mutation path, which writes an ``accept`` event back.

Algorithm v1 (``algorithm_version='budget-quantile-v1'``):

1. Bucket confirmed expenses by the project accounting contract:
   ``COALESCE(expense_time, confirmed_at)`` in the requested
   accounting timezone.
2. For each month, sum ``home_currency_amount`` per category. Months
   with zero spend in a category contribute a zero (because "I didn't
   spend on this category that month" is a valid data point — adding
   it makes the P50 reflect typical reality, not just "months I did
   spend"). The zero-contribution behaviour is gated by
   ``include_zero_months`` so callers can opt out.
3. Require at least ``min_months`` months of usable history.
4. Sort, take P50 and P75 by linear interpolation (matches numpy's
   default ``method='linear'`` without a numpy dependency).

Returns ``None`` for categories with too little history or empty
input. Caller persists via ``record_decision(decision_type=
'budget_suggestion')``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense
from app.services.learning_service._algorithm_registry import (
    BUDGET_SUGGESTION,
)
from app.services.spending_contract_service import (
    accounting_timezone_key,
    month_bounds_utc,
    month_labels_ending_at,
    shift_month,
    stat_month_label,
    stat_time_expr,
)
from app.services.time_service import ensure_utc, local_month_label, now_utc

# Source of truth lives in the algorithm registry.
ALGORITHM_VERSION = BUDGET_SUGGESTION.current_version
DEFAULT_LOOK_BACK_MONTHS = 6
DEFAULT_MIN_MONTHS = 3


@dataclass(frozen=True)
class BudgetQuantileSuggestion:
    category: str
    p50_cents: int
    p75_cents: int
    sample_months: int
    algorithm_version: str = ALGORITHM_VERSION


def _quantile(sorted_values: list[int], q: float) -> int:
    """Linear-interpolated quantile, integer cents output.

    Equivalent to numpy's ``percentile(values, q*100, method='linear')``
    but without the dependency.
    """

    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return int(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    lower_idx = int(pos)
    upper_idx = min(lower_idx + 1, len(sorted_values) - 1)
    weight = pos - lower_idx
    lower = sorted_values[lower_idx]
    upper = sorted_values[upper_idx]
    return int(round(lower + (upper - lower) * weight))


def _lookback_months(
    *, now: datetime, look_back_months: int, timezone_name: str | None
) -> list[str]:
    timezone_key = accounting_timezone_key(timezone_name)
    current_month = local_month_label(ensure_utc(now), timezone_key)
    if current_month is None:
        return []
    last_closed_month = shift_month(current_month, -1)
    return month_labels_ending_at(last_closed_month, look_back_months)


def compute_budget_quantile_suggestion(
    db: Session,
    *,
    tenant_id: str,
    category: str,
    look_back_months: int = DEFAULT_LOOK_BACK_MONTHS,
    min_months: int = DEFAULT_MIN_MONTHS,
    include_zero_months: bool = True,
    now: datetime | None = None,
    timezone_name: str | None = None,
) -> BudgetQuantileSuggestion | None:
    """Return the P50 / P75 monthly spend for ``category``.

    ``include_zero_months`` toggles whether months with no expense in
    the category contribute a zero data point. The default (True)
    reflects the user's *actual* per-month cadence; turning it off is
    useful when the user explicitly only wants to see "months I spent
    on this".
    """

    look_back_months = max(int(look_back_months), 1)
    anchor = ensure_utc(now) or now_utc()
    months = _lookback_months(
        now=anchor,
        look_back_months=look_back_months,
        timezone_name=timezone_name,
    )
    if not months:
        return None
    earliest_start, _ = month_bounds_utc(months[0], timezone_name)
    _, latest_end = month_bounds_utc(months[-1], timezone_name)
    time_expr = stat_time_expr()

    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(Expense.category == category)
        .where(Expense.amount_cents.is_not(None))
        .where(time_expr >= earliest_start)
        .where(time_expr < latest_end)
    )

    monthly_totals: dict[str, int] = defaultdict(int)
    timezone_key = accounting_timezone_key(timezone_name)
    for expense in expenses:
        key = stat_month_label(expense, timezone_key)
        if key not in months:
            continue
        monthly_totals[key] += int(expense.amount_cents or 0)

    if include_zero_months:
        # Pad missing months with zero so the user's cadence is
        # accurately reflected. Without this, a user who only spends
        # on this category once a quarter sees a P50 equal to "one
        # quarter's spend" which over-estimates the typical month.
        for month in months:
            monthly_totals.setdefault(month, 0)

    values = sorted(int(v) for v in monthly_totals.values())
    if len(values) < max(min_months, 1):
        return None

    p50 = _quantile(values, 0.5)
    p75 = _quantile(values, 0.75)
    return BudgetQuantileSuggestion(
        category=category,
        p50_cents=p50,
        p75_cents=p75,
        sample_months=len(values),
    )


__all__ = [
    "ALGORITHM_VERSION",
    "BudgetQuantileSuggestion",
    "compute_budget_quantile_suggestion",
]
