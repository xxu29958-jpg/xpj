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
    return [
        CategorySnapshot(
            category=row.category,
            amount_cents=int(row.amount_cents),
            count=int(row.count),
        )
        for row in report.top_categories
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
    for category in [item.category for item in report.top_categories]:
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
                category=category,
                median_cents=int(explanation.p50_cents),
                p75_cents=int(explanation.p75_cents),
            )
        )
    return rows
