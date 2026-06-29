"""v1.2 P2 — analytical "radar" views: cashflow + subscription.

Two read-only signal generators over the confirmed-expense / income
plan corpus. Both return plain dataclasses; rendering and storage as
algorithm_decisions is the caller's job.

* :func:`cashflow_radar` — per-month net flow (income − expenses) for
  the last N months. The UI shows it as a trend chart so the user can
  spot a deteriorating monthly cadence before it becomes a problem.
* :func:`subscription_radar` — heuristic detector for "this merchant
  charges you roughly the same amount on roughly the same day every
  month for K consecutive months". Surfaces as candidate recurring
  items; the user confirms / dismisses via the existing recurring
  workflow which records the learning event.

Both functions are pure reads; nothing mutates here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense
from app.services.income_plan_service import total_monthly_income_cents
from app.services.spending_contract_service import (
    accounting_timezone_key,
    month_bounds_utc,
    month_labels_ending_at,
    stat_month_label,
    stat_time_expr,
)
from app.services.time_service import ensure_utc, local_month_label, now_utc

DEFAULT_CASHFLOW_LOOK_BACK_MONTHS = 6
DEFAULT_SUBSCRIPTION_LOOK_BACK_MONTHS = 6
DEFAULT_SUBSCRIPTION_MIN_OCCURRENCES = 3
SUBSCRIPTION_AMOUNT_TOLERANCE_PCT = 0.10  # ±10%


@dataclass(frozen=True)
class CashflowMonth:
    """One row of the cashflow radar — the cleaned-up monthly net."""

    year_month: str
    income_cents: int
    expense_cents: int

    @property
    def net_cents(self) -> int:
        return self.income_cents - self.expense_cents


@dataclass(frozen=True)
class SubscriptionCandidate:
    """A merchant the user appears to be on a recurring charge with."""

    merchant: str
    typical_amount_cents: int
    occurrences: int
    months_covered: int
    last_seen_month: str


def _months_back(
    now: datetime, look_back: int, timezone_name: str | None
) -> list[str]:
    """Return YYYY-MM strings for the last ``look_back`` months
    (inclusive of the current month) in chronological order.

    Calendar-correct: walks backward exactly N months instead of
    subtracting 30 days each step, so February isn't dropped from a
    six-month window ending in April.
    """

    timezone_key = accounting_timezone_key(timezone_name)
    current = local_month_label(ensure_utc(now), timezone_key)
    if current is None:
        return []
    return month_labels_ending_at(current, max(int(look_back), 1))


def cashflow_radar(
    db: Session,
    *,
    tenant_id: str,
    look_back_months: int = DEFAULT_CASHFLOW_LOOK_BACK_MONTHS,
    now: datetime | None = None,
    timezone_name: str | None = None,
) -> list[CashflowMonth]:
    """Return ``CashflowMonth`` rows for the last N months, oldest
    first. Months with zero income AND zero expense are still emitted
    (with both at 0) so the time series has no gaps."""

    look_back_months = max(int(look_back_months), 1)
    anchor = ensure_utc(now) or now_utc()
    months = _months_back(anchor, look_back_months, timezone_name)
    if not months:
        return []
    start_utc, _ = month_bounds_utc(months[0], timezone_name)
    _, end_utc = month_bounds_utc(months[-1], timezone_name)
    time_expr = stat_time_expr()

    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(Expense.amount_cents.is_not(None))
        .where(time_expr >= start_utc)
        .where(time_expr < end_utc)
    )
    expense_by_month: dict[str, int] = defaultdict(int)
    timezone_key = accounting_timezone_key(timezone_name)
    for expense in expenses:
        key = stat_month_label(expense, timezone_key)
        if key in months:
            expense_by_month[key] += int(expense.amount_cents or 0)

    return [
        CashflowMonth(
            year_month=month,
            income_cents=total_monthly_income_cents(
                db,
                tenant_id=tenant_id,
                month=month,
            ),
            expense_cents=int(expense_by_month.get(month, 0)),
        )
        for month in months
    ]


def subscription_radar(
    db: Session,
    *,
    tenant_id: str,
    look_back_months: int = DEFAULT_SUBSCRIPTION_LOOK_BACK_MONTHS,
    min_occurrences: int = DEFAULT_SUBSCRIPTION_MIN_OCCURRENCES,
    amount_tolerance_pct: float = SUBSCRIPTION_AMOUNT_TOLERANCE_PCT,
    now: datetime | None = None,
    timezone_name: str | None = None,
) -> list[SubscriptionCandidate]:
    """Return merchants the user appears to be paying every month.

    Heuristic v1: group confirmed expenses by merchant, ignore
    merchants seen in fewer than ``min_occurrences`` distinct months,
    require all occurrences to be within ``±amount_tolerance_pct`` of
    the merchant's median amount.
    """

    anchor = ensure_utc(now) or now_utc()
    months_window = _months_back(anchor, look_back_months, timezone_name)
    if not months_window:
        return []
    start_utc, _ = month_bounds_utc(months_window[0], timezone_name)
    _, end_utc = month_bounds_utc(months_window[-1], timezone_name)
    time_expr = stat_time_expr()

    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(time_expr >= start_utc)
        .where(time_expr < end_utc)
        .where(Expense.merchant.is_not(None))
        .where(Expense.amount_cents.is_not(None))
    )

    per_merchant: dict[str, list[tuple[str, int]]] = defaultdict(list)
    timezone_key = accounting_timezone_key(timezone_name)
    for expense in expenses:
        merchant_key = (expense.merchant or "").strip()
        if not merchant_key:
            continue
        month_key = stat_month_label(expense, timezone_key)
        if month_key not in months_window:
            continue
        per_merchant[merchant_key].append(
            (month_key, int(expense.amount_cents or 0))
        )

    candidates: list[SubscriptionCandidate] = []
    for merchant_key, entries in per_merchant.items():
        if len(entries) < min_occurrences:
            continue
        # Distinct-month count is the real signal — multiple charges
        # in one month from one merchant don't make a subscription.
        distinct_months = {month for month, _ in entries}
        if len(distinct_months) < min_occurrences:
            continue
        amounts = sorted(amount for _, amount in entries)
        median = amounts[len(amounts) // 2]
        if median == 0:
            continue
        tolerance = max(int(median * amount_tolerance_pct), 1)
        if any(abs(a - median) > tolerance for a in amounts):
            continue
        last_seen = max(month for month, _ in entries)
        candidates.append(
            SubscriptionCandidate(
                merchant=merchant_key,
                typical_amount_cents=int(median),
                occurrences=len(entries),
                months_covered=len(distinct_months),
                last_seen_month=last_seen,
            )
        )
    candidates.sort(
        key=lambda c: (c.months_covered, c.typical_amount_cents),
        reverse=True,
    )
    return candidates


__all__ = [
    "CashflowMonth",
    "SubscriptionCandidate",
    "cashflow_radar",
    "subscription_radar",
]
