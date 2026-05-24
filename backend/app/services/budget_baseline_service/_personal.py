"""Rolling personal P50 / P75 per category from confirmed expenses.

Once a user has a few months of confirmed data, their own spend
distribution beats any BLS / 50-30-20 default. This module computes
per-category median and 75th percentile over a configurable rolling
window so :mod:`_blend` can fade from default to personal as
``months_observed`` grows.

Reads only the ``confirmed`` slice of expenses (rejected / pending are
not real spend signals). Aggregation time column is the project
standard ``COALESCE(expense_time, confirmed_at)`` per
``spending_contract_service.stat_time_expr`` — keeps the personal
baseline aligned with the same window every other report uses.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger_scope import add_ledger_scope
from app.models import Expense
from app.services.budget_baseline_service._models import CategoryBaseline
from app.services.category_service import normalize_category
from app.services.spending_contract_service import stat_time_expr
from app.services.time_service import now_utc


@dataclass(frozen=True)
class PersonalBaseline:
    """Per-category P50 / P75 over a rolling window.

    ``months_observed`` is the number of full months covered by the
    underlying data, used downstream to decide how much to trust this
    baseline relative to the default (more months → higher weight).
    """

    months_observed: int
    categories: tuple[CategoryBaseline, ...]


def compute_personal_baseline(
    db: Session,
    *,
    tenant_id: str,
    months_window: int = 6,
    now: datetime | None = None,
) -> PersonalBaseline:
    """Aggregate confirmed expenses over the last ``months_window`` full
    calendar months into per-category P50 / P75 baselines.

    Returns an empty ``PersonalBaseline`` when no confirmed data exists
    in the window — callers should fall back to the default baseline.
    """
    if months_window <= 0:
        raise ValueError("months_window must be positive")
    anchor = now or now_utc()
    start_utc = anchor - timedelta(days=months_window * 31)

    rows = list(
        db.scalars(
            add_ledger_scope(select(Expense), Expense, tenant_id)
            .where(Expense.status == "confirmed")
            .where(Expense.amount_cents.is_not(None))
            .where(stat_time_expr() >= start_utc)
            .where(stat_time_expr() <= anchor)
        )
    )
    if not rows:
        return PersonalBaseline(months_observed=0, categories=())

    monthly_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    months_seen: set[str] = set()
    for expense in rows:
        bucket_time = expense.expense_time or expense.confirmed_at
        if bucket_time is None:
            continue
        month_key = bucket_time.strftime("%Y-%m")
        months_seen.add(month_key)
        category = normalize_category(expense.category or "")
        monthly_totals[category][month_key] += int(expense.amount_cents)

    categories: list[CategoryBaseline] = []
    for category, by_month in monthly_totals.items():
        monthly_amounts = sorted(by_month.values())
        # P50 = median; P75 via inclusive percentile.
        median = int(statistics.median(monthly_amounts))
        p75 = _percentile_inclusive(monthly_amounts, 75)
        categories.append(
            CategoryBaseline(
                category=category,
                median_cents=median,
                p75_cents=max(p75, median),
            )
        )

    categories.sort(key=lambda row: -row.median_cents)
    return PersonalBaseline(
        months_observed=len(months_seen),
        categories=tuple(categories),
    )


def _percentile_inclusive(values: list[int], percentile: int) -> int:
    """Inclusive percentile (matches numpy's default ``linear`` method)
    without bringing numpy in. Returns an int cents value."""
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    rank = (percentile / 100) * (len(values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    interpolated = values[lower] * (1 - weight) + values[upper] * weight
    return int(round(interpolated))
