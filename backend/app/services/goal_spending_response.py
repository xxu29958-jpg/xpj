"""Spending-goal progress compares confirmed spending in the target's recorded currency."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Goal
from app.money_contract import projection_sum_to_int
from app.schemas import GoalResponse
from app.services.money_projection_service import sum_projected_amounts
from app.services.spending_contract_service import calendar_month_bounds, undated_expense_counts_by_category
from app.services.spending_projection_service import projected_category_spend, read_spending_period


class GoalSpendTotals:
    def __init__(self, total_amount_cents: int | None, by_category: dict[str, int | None], *, home_currency_code: str | None, undated_by_category: dict[str, int] | None = None) -> None:
        self.total_amount_cents = total_amount_cents
        self.by_category = by_category
        self.home_currency_code = home_currency_code
        self.undated_by_category = undated_by_category or {}


def month_spend_totals(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    home_currency_code: str | None,
    timezone_name: str | None = None,
) -> GoalSpendTotals:
    if home_currency_code is None:
        undated = undated_expense_counts_by_category(db, tenant_id=tenant_id)
        return GoalSpendTotals(None, {}, home_currency_code=None, undated_by_category=undated)
    projection = read_spending_period(db, tenant_id=tenant_id, ranges=[calendar_month_bounds(month)],
        timezone_name=timezone_name, home=home_currency_code)
    spending = projected_category_spend(projection.entries)
    undated = projection.undated_by_category
    by_category = {category: value.amount_cents for category, value in spending.items()}
    for category in undated:
        by_category[category] = None
    return GoalSpendTotals(
        sum_projected_amounts(by_category.values(), label="goal_spending.total"),
        by_category, home_currency_code=home_currency_code, undated_by_category=undated,
    )


def _progress_state(goal: Goal, spent_amount_cents: int | None) -> str:
    if goal.status == "archived":
        return "archived"
    if spent_amount_cents is None:
        return "unavailable"
    if spent_amount_cents <= 0:
        return "not_started"
    if spent_amount_cents >= goal.target_amount_cents:
        return "over_limit"
    if spent_amount_cents * 100 >= goal.target_amount_cents * 80:
        return "near_limit"
    return "on_track"


def goal_response(goal: Goal, totals: GoalSpendTotals) -> GoalResponse:
    spent = totals.by_category.get(goal.category, 0) if goal.category else totals.total_amount_cents
    if goal.home_currency_code is None or goal.home_currency_code != totals.home_currency_code:
        spent = None
    target = projection_sum_to_int(
        goal.target_amount_cents,
        label="goal_spending.target",
    )
    remaining = None if spent is None else projection_sum_to_int(
        target - spent,
        label="goal_spending.remaining",
    )
    return GoalResponse(
        public_id=goal.public_id,
        ledger_id=goal.tenant_id,
        name=goal.name,
        goal_type=goal.goal_type,
        period=goal.period,
        home_currency_code=goal.home_currency_code,
        month=goal.month,
        category=goal.category,
        target_amount_cents=target,
        spent_amount_cents=spent,
        undated_expense_count=(totals.undated_by_category.get(goal.category, 0) if goal.category
            else sum(totals.undated_by_category.values())),
        remaining_amount_cents=remaining,
        # Display progress is a bounded range value. Exact overage remains in
        # spent/target/remaining and ``progress_state=over_limit``; emitting an
        # unbounded percentage would be both inaccessible as a progressbar and
        # unsafe for ECMAScript consumers after C07 aggregate widening.
        progress_percent=None if spent is None else max(0, min(100, (spent * 100) // target)),
        progress_state=_progress_state(goal, spent),
        status=goal.status,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        row_version=goal.row_version,
        archived_at=goal.archived_at,
    )
