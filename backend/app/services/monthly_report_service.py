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

from sqlalchemy.orm import Session

from app.services.learning_service._budget_quantile import (
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

    rows = db.scalars(
        confirmed_amount_query(
            tenant_id=tenant_id,
            month=year_month,
            timezone_name=timezone_name,
        )
    )
    return [
        (expense.category or "其他", int(expense.amount_cents or 0))
        for expense in rows
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
    total = sum(amount for _, amount in rows)
    by_category: dict[str, int] = defaultdict(int)
    count_by_category: dict[str, int] = defaultdict(int)
    for category, amount in rows:
        by_category[category] += amount
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
    prev_total = sum(amount for _, amount in prev_rows)
    delta = total - prev_total
    delta_pct: float | None = None
    if prev_total > 0:
        delta_pct = (delta / prev_total) * 100.0

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
    actual = sum(amount for cat, amount in rows if cat == category)

    # Anchor the quantile lookback at the start of THIS month so the
    # month we're explaining doesn't pollute its own baseline.
    anchor_start, _ = month_bounds_utc(year_month, timezone_name)
    suggestion = compute_budget_quantile_suggestion(
        db,
        tenant_id=tenant_id,
        category=category,
        now=anchor_start,
        min_months=3,
        timezone_name=timezone_name,
    )

    # "All-zero baseline" (every padded month had zero spend in this
    # category) is functionally the same as no history at all — the
    # quantile is 0 and any non-zero current spend would flag as
    # "over_p75", which is unhelpful noise. Treat it as no_history
    # explicitly.
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

    delta = actual - suggestion.p75_cents
    if actual <= suggestion.p50_cents:
        verdict = "under"
    elif actual <= suggestion.p75_cents:
        verdict = "on_track"
    else:
        verdict = "over_p75"
    return BudgetExplanation(
        category=category,
        year_month=year_month,
        actual_cents=actual,
        p50_cents=suggestion.p50_cents,
        p75_cents=suggestion.p75_cents,
        delta_vs_p75_cents=delta,
        verdict=verdict,
    )


__all__ = [
    "BudgetExplanation",
    "CategoryRollup",
    "MonthlyReport",
    "compose_budget_explanation",
    "compose_monthly_report",
]
