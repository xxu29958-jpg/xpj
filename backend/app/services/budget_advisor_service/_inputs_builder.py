"""Assemble anonymised advisor inputs from the monthly report layer.

The AI advisor receives the same aggregate facts the user sees in the
monthly report surface: category totals and historical budget baselines.
It does not read receipt images, notes, true merchant names, member names,
or per-row ledger records. Suggestions returned by the provider remain
read-only until a user applies them through the normal budget UI.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import RecurringItem
from app.services.budget_advisor_service._models import (
    ALLOWED_INCOME_SOURCE_TYPES,
    BudgetInputs,
    CategorySnapshot,
    HistoricalBaseline,
    IncomePlanSnapshot,
)
from app.services.category_common import DEFAULT_CATEGORIES, normalize_category
from app.services.income_plan_service import list_income_plans
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
        income_plan=_income_plan(db, tenant_id=tenant_id),
        recurring_total_monthly_cents=_recurring_total_monthly_cents(db, tenant_id=tenant_id),
        recurring_active_count=_recurring_active_count(db, tenant_id=tenant_id),
    )


def _active_recurring_items(db: Session, *, tenant_id: str) -> list[RecurringItem]:
    return list(
        db.scalars(
            ledger_scoped_select(RecurringItem, tenant_id).where(
                RecurringItem.status == "active"
            )
        )
    )


def _recurring_total_monthly_cents(db: Session, *, tenant_id: str) -> int:
    """Aggregate monthly recurring commitment. Coarse magnitude only —
    recurring rows are merchant-keyed (PII), so no per-item / per-merchant
    detail leaves the device; the advisor sees just the total."""
    return sum(int(item.last_amount_cents) for item in _active_recurring_items(db, tenant_id=tenant_id))


def _recurring_active_count(db: Session, *, tenant_id: str) -> int:
    return len(_active_recurring_items(db, tenant_id=tenant_id))


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


def _income_plan(db: Session, *, tenant_id: str) -> list[IncomePlanSnapshot]:
    """Active income plans as advisor input. ``source_type`` is generalised to a
    PII-free allowlist; the free-text ``label`` is intentionally never sent."""
    return [
        IncomePlanSnapshot(
            source_type=_generalize_source_type(plan.source_type),
            amount_cents=int(plan.amount_cents),
            pay_day=int(plan.pay_day),
        )
        for plan in list_income_plans(db, tenant_id=tenant_id, status="active")
    ]


def _generalize_source_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in ALLOWED_INCOME_SOURCE_TYPES else "other"


def _advisor_category(category: str | None) -> str:
    normalized = normalize_category(category)
    if normalized in DEFAULT_CATEGORIES:
        return normalized
    return DEFAULT_CATEGORIES[-1]
