"""Stage sticky debt-goal achievement at completed command boundaries."""
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CreditFacility, Debt, DebtGoalLink, Goal
from app.services.goal_debt_repayment_core import stage_locked_goal_achievement


def stage_debt_goal_achievements(
    db: Session,
    *,
    debt_ids: Iterable[int] = (),
    account_ids: Iterable[int] = (),
) -> None:
    """Stage achievement for explicit affected facts, without committing them.

    Call only after the complete business command has staged every correction,
    replacement and allocation. In particular, a temporary zero balance while
    reversing an expense is not an achievement.
    """
    affected = set(debt_ids)
    accounts = set(account_ids)
    db.flush()
    if accounts:
        affected.update(db.scalars(select(CreditFacility.debt_id).where(CreditFacility.account_id.in_(accounts))))
    if not affected:
        return
    # Link publication uses this same Debt -> Goal lock order. Acquiring Debt
    # first closes the race between a new link and its last repayment.
    debts = list(db.scalars(select(Debt).where(Debt.id.in_(affected)).order_by(Debt.id).with_for_update()))
    goals = db.scalars(select(Goal).where(
        Goal.tenant_id.in_({debt.tenant_id for debt in debts}), Goal.goal_type == "debt_repayment",
        select(DebtGoalLink.goal_id).where(
            DebtGoalLink.debt_id.in_([debt.id for debt in debts]), DebtGoalLink.goal_version == Goal.goal_version,
            DebtGoalLink.goal_id == Goal.id,
        ).exists())
        .order_by(Goal.id).with_for_update().execution_options(populate_existing=True))
    for goal in goals:
        stage_locked_goal_achievement(db, goal)
