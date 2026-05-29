"""Assemble anonymised advisor inputs from the monthly report layer.

The AI advisor receives the same aggregate facts the user sees in the
monthly report surface: category totals and historical budget baselines.
It does not read receipt images, notes, true merchant names, member names,
or per-row ledger records. Suggestions returned by the provider remain
read-only until a user applies them through the normal budget UI.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.budget_advisor_service._models import (
    BudgetInputs,
    CategorySnapshot,
    HistoricalBaseline,
)
from app.services.category_common import DEFAULT_CATEGORIES, normalize_category
from app.services.monthly_report_service import (
    MonthlyReport,
    compose_budget_explanation,
    compose_monthly_report,
)


def build_budget_inputs(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str = "Asia/Shanghai",
    home_currency: str = "CNY",
) -> BudgetInputs:
    """Build advisor input from anonymised monthly-report aggregates."""

    report = compose_monthly_report(
        db,
        tenant_id=tenant_id,
        year_month=month,
        top_n=20,
        timezone_name=timezone_name,
    )
    return BudgetInputs(
        month=month,
        home_currency=home_currency,
        category_breakdown=_category_breakdown(report),
        historical_baseline=_historical_baseline(
            db,
            tenant_id=tenant_id,
            month=month,
            report=report,
            timezone_name=timezone_name,
        ),
    )


def _category_breakdown(report: MonthlyReport) -> list[CategorySnapshot]:
    grouped: dict[str, tuple[int, int]] = {}
    for row in report.top_categories:
        category = _advisor_category(row.category)
        amount, count = grouped.get(category, (0, 0))
        grouped[category] = (
            amount + int(row.amount_cents),
            count + int(row.count),
        )
    return [
        CategorySnapshot(category=category, amount_cents=amount, count=count)
        for category, (amount, count) in grouped.items()
    ]


def _historical_baseline(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    report: MonthlyReport,
    timezone_name: str,
) -> list[HistoricalBaseline]:
    rows: list[HistoricalBaseline] = []
    seen_categories: set[str] = set()
    for category in [item.category for item in report.top_categories]:
        advisor_category = _advisor_category(category)
        # De-dupe by canonical category. compose_budget_explanation aggregates
        # the whole alias group (canonical + legacy aliases), so the first raw
        # member already covers the rest — skipping later aliases drops no
        # history, it just avoids emitting the same canonical baseline twice.
        if advisor_category in seen_categories:
            continue
        seen_categories.add(advisor_category)
        explanation = compose_budget_explanation(
            db,
            tenant_id=tenant_id,
            category=category,
            year_month=month,
            timezone_name=timezone_name,
        )
        if explanation.p50_cents is None or explanation.p75_cents is None:
            continue
        rows.append(
            HistoricalBaseline(
                category=advisor_category,
                median_cents=int(explanation.p50_cents),
                p75_cents=int(explanation.p75_cents),
            )
        )
    return rows


def _advisor_category(category: str | None) -> str:
    normalized = normalize_category(category)
    if normalized in DEFAULT_CATEGORIES:
        return normalized
    return DEFAULT_CATEGORIES[-1]
