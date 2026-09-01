"""v1.2 P3 — monthly report + budget explanation layer.

Two read-side services:

* :func:`compose_monthly_report` — pull the user's spending for a
  named month, compare to last month and the trailing P50 / P75, and
  produce a structured ``MonthlyReport`` the UI can render as "本月
  花了 X，比上月多 Y%，主要花在 Z 和 W" without an AI call.
* :func:`compose_budget_explanation` — for a given budget category,
  explain why it's over / under / on track this month. Same shape:
  numbers first, narrative is the UI's job.

Both functions hit the ledger directly and never write. AI advisor
integration (using the existing P2 batch-2 ``budget_advisor_service``
framework) lives in the route layer, where the structured payload
produced here becomes the anonymised input — keeping the privacy
boundary intact.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.money_contract import (
    projection_sum_to_int,
    projection_values_sum_to_int,
)
from app.services.category_common import category_filter_values
from app.services.learning_service._budget_quantile import (
    BudgetQuantileSuggestion,
    compute_budget_quantile_suggestion,
)
from app.services.spending_contract_service import (
    confirmed_amount_query,
    month_bounds_utc,
    shift_month,
)


@dataclass(frozen=True)
class CategoryRollup:
    category: str
    amount_cents: int
    count: int = 0


@dataclass(frozen=True)
class MonthlyReport:
    year_month: str
    total_cents: int
    expense_count: int
    top_categories: list[CategoryRollup] = field(default_factory=list)
    delta_vs_previous_cents: int = 0
    delta_pct: float | None = None


@dataclass(frozen=True)
class BudgetExplanation:
    """Per-category insight for the month under review."""

    category: str
    year_month: str
    actual_cents: int
    p50_cents: int | None
    p75_cents: int | None
    delta_vs_p75_cents: int | None
    verdict: str  # "under" / "on_track" / "over_p75" / "no_history"


def _budget_explanation(
    *,
    category: str,
    year_month: str,
    actual: int,
    suggestion: BudgetQuantileSuggestion | None,
) -> BudgetExplanation:
    if suggestion is None or (
        suggestion.p50_cents == 0 and suggestion.p75_cents == 0
    ):
        return BudgetExplanation(
            category=category,
            year_month=year_month,
            actual_cents=actual,
            p50_cents=None,
            p75_cents=None,
            delta_vs_p75_cents=None,
            verdict="no_history",
        )
    p50 = projection_sum_to_int(suggestion.p50_cents, label="monthly_report.p50")
    p75 = projection_sum_to_int(suggestion.p75_cents, label="monthly_report.p75")
    delta = projection_sum_to_int(
        actual - p75,
        label="monthly_report.delta_vs_p75",
    )
    verdict = "under" if actual <= p50 else "on_track" if actual <= p75 else "over_p75"
    return BudgetExplanation(
        category=category,
        year_month=year_month,
        actual_cents=actual,
        p50_cents=p50,
        p75_cents=p75,
        delta_vs_p75_cents=delta,
        verdict=verdict,
    )


def _previous_month(year_month: str) -> str:
    return shift_month(year_month, -1)


def _confirmed_in_month(
    db: Session,
    *,
    tenant_id: str,
    year_month: str,
    timezone_name: str | None,
) -> list[tuple[str, int]]:
    """Return (category, amount_cents) pairs for the named month."""

    rows = db.execute(
        confirmed_amount_query(
            tenant_id=tenant_id,
            month=year_month,
            timezone_name=timezone_name,
        )
    )
    return [
        (
            row.category or "其他",
            projection_sum_to_int(
                row.amount_cents,
                label="monthly_report.entry",
                empty_is_zero=True,
            ),
        )
        for row in rows
    ]


def compose_monthly_report(
    db: Session,
    *,
    tenant_id: str,
    year_month: str,
    top_n: int = 5,
    timezone_name: str | None = None,
) -> MonthlyReport:
    """Build the month's summary card. ``top_n`` controls how many
    category rollups land in ``top_categories``."""

    rows = _confirmed_in_month(
        db,
        tenant_id=tenant_id,
        year_month=year_month,
        timezone_name=timezone_name,
    )
    total = projection_values_sum_to_int(
        (amount for _, amount in rows),
        label="monthly_report.total",
    )
    by_category: dict[str, int] = defaultdict(int)
    count_by_category: dict[str, int] = defaultdict(int)
    for category, amount in rows:
        by_category[category] = projection_sum_to_int(
            by_category[category] + amount,
            label="monthly_report.category",
        )
        count_by_category[category] += 1
    top = sorted(
        (
            CategoryRollup(
                category=c,
                amount_cents=a,
                count=count_by_category[c],
            )
            for c, a in by_category.items()
        ),
        key=lambda r: r.amount_cents,
        reverse=True,
    )[: max(top_n, 0)]

    prev = _previous_month(year_month)
    prev_rows = _confirmed_in_month(
        db, tenant_id=tenant_id, year_month=prev, timezone_name=timezone_name
    )
    prev_total = projection_values_sum_to_int(
        (amount for _, amount in prev_rows),
        label="monthly_report.previous_total",
    )
    delta = projection_sum_to_int(
        total - prev_total,
        label="monthly_report.delta",
    )
    delta_pct: float | None = None
    if prev_total > 0:
        delta_pct = float(
            Decimal(delta) * Decimal(100) / Decimal(prev_total)
        )

    return MonthlyReport(
        year_month=year_month,
        total_cents=total,
        expense_count=len(rows),
        top_categories=top,
        delta_vs_previous_cents=delta,
        delta_pct=delta_pct,
    )


def compose_budget_explanation(
    db: Session,
    *,
    tenant_id: str,
    category: str,
    year_month: str,
    timezone_name: str | None = None,
) -> BudgetExplanation:
    """Compare this month's category spend against the trailing P50 /
    P75 derived from the same tenant's history."""

    rows = _confirmed_in_month(
        db,
        tenant_id=tenant_id,
        year_month=year_month,
        timezone_name=timezone_name,
    )
    # Aggregate the canonical category together with its legacy aliases (e.g.
    # '餐饮' folds in legacy '吃饭') so both the actual spend and the trailing
    # baseline cover the same set the category breakdown rolls up under — a
    # caller passing any alias of the group gets the whole group's history.
    category_values = category_filter_values(category)
    actual = projection_values_sum_to_int(
        (
            amount
            for cat, amount in rows
            if cat in category_values
        ),
        label="monthly_report.category_actual",
    )

    # Anchor the quantile lookback at the start of THIS month so the
    # month we're explaining doesn't pollute its own baseline.
    anchor_start, _ = month_bounds_utc(year_month, timezone_name)
    suggestion = compute_budget_quantile_suggestion(
        db,
        tenant_id=tenant_id,
        category=category,
        categories=category_values,
        now=anchor_start,
        min_months=3,
        timezone_name=timezone_name,
    )

    return _budget_explanation(
        category=category,
        year_month=year_month,
        actual=actual,
        suggestion=suggestion,
    )


__all__ = [
    "BudgetExplanation",
    "CategoryRollup",
    "MonthlyReport",
    "compose_budget_explanation",
    "compose_monthly_report",
]
