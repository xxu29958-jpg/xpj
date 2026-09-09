"""One read owner for inspectable budget inputs and the complete private AI envelope."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import RecurringItem
from app.money_contract import projection_sum_to_int
from app.services.budget_advisor_service._models import (
    ALLOWED_INCOME_SOURCE_TYPES,
    BudgetInputs,
    CategorySnapshot,
    HistoricalBaseline,
    IncomePlanSnapshot,
)
from app.services.budget_baseline_service._discretionary import DiscretionaryBreakdown, compute_monthly_discretionary
from app.services.category_common import DEFAULT_CATEGORIES, category_filter_values, normalize_category
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code
from app.services.income_plan_service import income_forecast
from app.services.money_projection_service import ProjectionGap, ordered_projection_gaps
from app.services.monthly_report_service import MonthlyReport, compose_budget_explanation, compose_monthly_report
from app.services.recurring_occurrence_query import total_outstanding_recurring_cents
from app.services.recurring_service import recurring_monthly_total


@dataclass(frozen=True)
class BudgetInputProjection:
    month: str
    home_currency_code: str
    breakdown: DiscretionaryBreakdown
    missing_rates: tuple[ProjectionGap, ...]
    provider_inputs: BudgetInputs | None

    @property
    def inputs_fingerprint(self) -> str | None:
        """Invalidate cached advice when its private basis changes across clients."""
        if self.provider_inputs is None:
            return None
        payload = json.dumps(asdict(self.provider_inputs), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_budget_inputs(
    db: Session, *, tenant_id: str, month: str, home_currency_code: str | None = None,
    timezone_name: str = "Asia/Shanghai", savings_target_cents: int = 0, reserved_buffer_cents: int = 0,
) -> BudgetInputProjection:
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    report = compose_monthly_report(db, tenant_id=tenant_id, year_month=month, top_n=None,
        timezone_name=timezone_name, home_currency_code=home, compare_previous=False)
    gaps = set(report.missing_rates)
    baseline = _historical_baseline(db, tenant_id=tenant_id, month=month, report=report,
        timezone_name=timezone_name, home=home, gaps=gaps)
    forecast = income_forecast(db, tenant_id=tenant_id, month=month, timezone_name=timezone_name,
        home_currency_code=home, missing_rates=gaps)
    items = _active_recurring_items(db, tenant_id=tenant_id)
    recurring = recurring_monthly_total(db, tenant_id=tenant_id, items=items,
        home_currency_code=home, month=month, missing_rates=gaps)
    fixed = total_outstanding_recurring_cents(db, tenant_id=tenant_id, month=month,
        home_currency_code=home, missing_rates=gaps)
    breakdown = compute_monthly_discretionary(monthly_income_cents=forecast.expected_amount_cents,
        fixed_expenses_cents=fixed, spent_amount_cents=report.total_cents,
        savings_target_cents=savings_target_cents, reserved_buffer_cents=reserved_buffer_cents)
    inputs = None
    if not gaps:
        inputs = BudgetInputs(month=month, home_currency=home, category_breakdown=_category_breakdown(report),
            historical_baseline=baseline, income_plan=_income_snapshots(forecast),
            recurring_total_monthly_cents=recurring, recurring_active_count=len(items))
    return BudgetInputProjection(month, home, breakdown, ordered_projection_gaps(gaps), inputs)


def _active_recurring_items(db: Session, *, tenant_id: str) -> list[RecurringItem]:
    return list(db.scalars(ledger_scoped_select(RecurringItem, tenant_id).where(RecurringItem.status == "active")))


def _category_breakdown(report: MonthlyReport) -> list[CategorySnapshot]:
    grouped: dict[str, tuple[int, int]] = {}
    for row in report.top_categories:
        category = _advisor_category(row.category)
        amount, count = grouped.get(category, (0, 0))
        grouped[category] = (projection_sum_to_int(amount + projection_sum_to_int(
            row.amount_cents, label="budget_advisor.category_row"), label="budget_advisor.category_total"), count + row.count)
    return [CategorySnapshot(category, amount, count) for category, (amount, count) in grouped.items()]


def _historical_baseline(db, *, tenant_id, month, report, timezone_name, home, gaps) -> list[HistoricalBaseline]:
    rows: list[HistoricalBaseline] = []
    grouped: dict[str, set[str]] = {}
    for item in report.top_categories:
        grouped.setdefault(_advisor_category(item.category), set()).update(category_filter_values(item.category))
    for category, values in grouped.items():
        explanation = compose_budget_explanation(db, tenant_id=tenant_id, category=category, categories=values,
            year_month=month, timezone_name=timezone_name, home_currency_code=home)
        gaps.update(explanation.missing_rates)
        if explanation.p50_cents is not None and explanation.p75_cents is not None:
            rows.append(HistoricalBaseline(category, explanation.p50_cents, explanation.p75_cents))
    return rows


def _income_snapshots(forecast) -> list[IncomePlanSnapshot]:
    return [IncomePlanSnapshot(source_type=_generalize_source_type(plan.source_type),
        amount_cents=projection_sum_to_int(amount, label="budget_advisor.income_plan"), pay_day=int(plan.pay_day))
        for plan, amount in forecast.projected_entries]


def _generalize_source_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized in ALLOWED_INCOME_SOURCE_TYPES else "other"


def _advisor_category(category: str | None) -> str:
    normalized = normalize_category(category)
    return normalized if normalized in DEFAULT_CATEGORIES else DEFAULT_CATEGORIES[-1]
