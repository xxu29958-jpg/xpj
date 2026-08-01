"""Spending-limit goal serialization helpers.

Split out of :mod:`app.services.goal_service` so the mutation/lifecycle surface
(create / update / archive / restore) stays under the file-LOC gate. Pure
read-side: aggregate a tenant's confirmed spend for a month and render a
``GoalResponse`` for a spending_limit goal. No mutation, no debt-goal logic, so
this module never imports back into ``goal_service`` (one-directional).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Goal
from app.money_contract import projection_sum_to_int
from app.schemas import GoalResponse
from app.services.category_service import normalize_category
from app.services.spending_contract_service import confirmed_amount_query


class GoalSpendTotals:
    def __init__(self, total_amount_cents: int, by_category: dict[str, int]) -> None:
        self.total_amount_cents = total_amount_cents
        self.by_category = by_category


def month_spend_totals(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None = None,
) -> GoalSpendTotals:
    filtered = confirmed_amount_query(
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    ).subquery()
    rows = db.execute(
        select(
            filtered.c.category,
            func.coalesce(func.sum(filtered.c.amount_cents), 0),
        )
        .select_from(filtered)
        .group_by(filtered.c.category)
    )
    total_amount_cents = 0
    by_category: dict[str, int] = {}
    for category_raw, amount_value in rows:
        amount = projection_sum_to_int(
            amount_value,
            label="goal_spending.category",
            empty_is_zero=True,
        )
        total_amount_cents = projection_sum_to_int(
            total_amount_cents + amount,
            label="goal_spending.total",
        )
        category = normalize_category(category_raw)
        by_category[category] = projection_sum_to_int(
            by_category.get(category, 0) + amount,
            label="goal_spending.normalized_category",
        )
    return GoalSpendTotals(total_amount_cents, by_category)


def _progress_state(goal: Goal, spent_amount_cents: int) -> str:
    if goal.status == "archived":
        return "archived"
    if spent_amount_cents <= 0:
        return "not_started"
    if spent_amount_cents >= goal.target_amount_cents:
        return "over_limit"
    if spent_amount_cents * 100 >= goal.target_amount_cents * 80:
        return "near_limit"
    return "on_track"


def goal_response(goal: Goal, totals: GoalSpendTotals) -> GoalResponse:
    spent = totals.by_category.get(goal.category, 0) if goal.category else totals.total_amount_cents
    target = projection_sum_to_int(
        goal.target_amount_cents,
        label="goal_spending.target",
    )
    remaining = projection_sum_to_int(
        target - spent,
        label="goal_spending.remaining",
    )
    return GoalResponse(
        public_id=goal.public_id,
        ledger_id=goal.tenant_id,
        name=goal.name,
        goal_type=goal.goal_type,
        period=goal.period,
        month=goal.month,
        category=goal.category,
        target_amount_cents=target,
        spent_amount_cents=spent,
        remaining_amount_cents=remaining,
        # Display progress is a bounded range value. Exact overage remains in
        # spent/target/remaining and ``progress_state=over_limit``; emitting an
        # unbounded percentage would be both inaccessible as a progressbar and
        # unsafe for ECMAScript consumers after C07 aggregate widening.
        progress_percent=min(100, (spent * 100) // target),
        progress_state=_progress_state(goal, spent),
        status=goal.status,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        row_version=goal.row_version,
        archived_at=goal.archived_at,
    )
