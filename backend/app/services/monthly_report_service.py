"""Monthly spending and historical comparisons in one explicit display currency."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.money_contract import projection_sum_to_int
from app.services.category_common import category_filter_values, normalize_category
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code
from app.services.learning_service._budget_quantile import compute_budget_quantile_suggestion
from app.services.ledger_calendar_service import current_calendar
from app.services.money_projection_service import (
    ProjectionGap,
    ordered_projection_gaps,
    sum_projected_amounts,
)
from app.services.spending_contract_service import (
    calendar_month_bounds,
    month_bounds_utc,
    shift_month,
)
from app.services.spending_projection_service import entry_gaps, projected_category_spend, read_spending_period


@dataclass(frozen=True)
class CategoryRollup:
    category: str
    amount_cents: int | None
    count: int = 0


@dataclass(frozen=True)
class MonthlyReport:
    year_month: str
    home_currency_code: str
    total_cents: int | None
    expense_count: int
    top_categories: list[CategoryRollup] = field(default_factory=list)
    delta_vs_previous_cents: int | None = 0
    delta_pct: float | None = None
    missing_rates: tuple[ProjectionGap, ...] = ()
    undated_expense_count: int = 0


@dataclass(frozen=True)
class BudgetExplanation:
    category: str
    year_month: str
    home_currency_code: str
    actual_cents: int | None
    p50_cents: int | None
    p75_cents: int | None
    delta_vs_p75_cents: int | None
    verdict: str
    missing_rates: tuple[ProjectionGap, ...] = ()
    undated_expense_count: int = 0


def _period_category_spend(entries, period):
    return projected_category_spend(entry for entry in entries if period[0] <= entry.stream_date < period[1])


def _top_category_rollups(spend, top_n):
    # Unknown categories stay visible first; no invented zero or partial rank.
    top = sorted((CategoryRollup(category, row.amount_cents, row.count) for category, row in spend.items()),
        key=lambda row: (row.amount_cents is not None, -(row.amount_cents or 0), row.category))
    if top_n is not None:
        top = top[:max(top_n, 0)]
    return top


def compose_monthly_report(
    db: Session, *, tenant_id: str, year_month: str, top_n: int | None = 5,
    timezone_name: str | None = None, home_currency_code: str | None = None,
    compare_previous: bool = True,
) -> MonthlyReport:
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    gaps: set[ProjectionGap] = set()
    periods = [calendar_month_bounds(year_month)]
    if compare_previous:
        periods.append(calendar_month_bounds(shift_month(year_month, -1)))
    projection = read_spending_period(db, tenant_id=tenant_id, ranges=periods,
        timezone_name=timezone_name, home=home)
    gaps.update(entry_gaps(projection.entries))
    spend = _period_category_spend(projection.entries, periods[0])
    previous = _period_category_spend(projection.entries, periods[1]) if compare_previous else None
    undated = projection.undated_expense_count
    total = None if undated else sum_projected_amounts((row.amount_cents for row in spend.values()), label="monthly_report.total")
    prev_total = None if previous is None or undated else sum_projected_amounts(
        (row.amount_cents for row in previous.values()), label="monthly_report.previous_total")
    delta = None if total is None or prev_total is None else projection_sum_to_int(total - prev_total, label="monthly_report.delta")
    delta_pct = float(Decimal(delta) * 100 / Decimal(prev_total)) if delta is not None and prev_total > 0 else None
    top = _top_category_rollups(spend, top_n)
    return MonthlyReport(year_month=year_month, home_currency_code=home, total_cents=total,
        expense_count=sum(row.count for row in spend.values()), top_categories=top,
        delta_vs_previous_cents=delta, delta_pct=delta_pct, missing_rates=ordered_projection_gaps(gaps),
        undated_expense_count=undated)


def _budget_verdict(actual, suggestion, gaps, undated):
    p50, p75 = (suggestion.p50_cents, suggestion.p75_cents) if suggestion else (None, None)
    delta = None
    if gaps or actual is None or undated:
        verdict = "projection_unavailable"
    elif suggestion is None or (p50 == 0 and p75 == 0):
        p50, p75, verdict = None, None, "no_history"
    else:
        delta = projection_sum_to_int(actual - p75, label="monthly_report.delta_vs_p75")
        verdict = "under" if actual <= p50 else "on_track" if actual <= p75 else "over_p75"
    return p50, p75, delta, verdict


def compose_budget_explanation(
    db: Session, *, tenant_id: str, category: str, year_month: str,
    timezone_name: str | None = None, home_currency_code: str | None = None,
    categories: set[str] | None = None,
) -> BudgetExplanation:
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    gaps: set[ProjectionGap] = set()
    values = categories if categories is not None else category_filter_values(category)
    normalized = {normalize_category(value) for value in values}
    projection = read_spending_period(db, tenant_id=tenant_id, ranges=[calendar_month_bounds(year_month)],
        timezone_name=timezone_name, home=home)
    selected = [entry for entry in projection.entries if entry.category in normalized]
    gaps.update(entry_gaps(selected))
    spend = projected_category_spend(selected)
    undated = sum(projection.undated_by_category.get(name, 0) for name in normalized)
    actual = None if undated else sum_projected_amounts((row.amount_cents for row in spend.values()), label="monthly_report.category_actual")
    timezone_name = current_calendar(db, ledger_id=tenant_id).timezone_name
    anchor, _ = month_bounds_utc(year_month, timezone_name)
    suggestion = compute_budget_quantile_suggestion(db, tenant_id=tenant_id, category=category,
        categories=values, now=anchor, min_months=3, timezone_name=timezone_name, home_currency_code=home)
    if suggestion is not None:
        gaps.update(suggestion.missing_rates)
        undated = max(undated, suggestion.undated_expense_count)
    p50, p75, delta, verdict = _budget_verdict(actual, suggestion, gaps, undated)
    return BudgetExplanation(category=normalize_category(category), year_month=year_month, home_currency_code=home,
        actual_cents=actual, p50_cents=p50, p75_cents=p75, delta_vs_p75_cents=delta,
        verdict=verdict, missing_rates=ordered_projection_gaps(gaps), undated_expense_count=undated)


__all__ = ["BudgetExplanation", "CategoryRollup", "MonthlyReport", "compose_budget_explanation", "compose_monthly_report"]
