"""The existing Debt reads its revolving obligation from the native funds facts."""
from datetime import datetime

from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import Session, aliased, object_session

from app.errors import AppError
from app.models import (
    AccountMovement,
    CreditFacility,
    CreditSettlementAllocation,
    Debt,
    FinancialAccount,
    Repayment,
    RepaymentVoid,
)
from app.money_contract import projection_sum_to_int, round_minor_ratio_half_up
from app.services.credit_allocation_service import (
    active_allocation_condition,
    active_credit_movements,
    allocation_totals,
)
from app.services.funds_visibility import account_scope
from app.services.time_service import ensure_utc


def uses_credit_at(db, debt, cutoff):
    if debt.source_type != "credit_facility":
        return False
    boundary = db.scalar(select(CreditFacility.adopted_at).where(CreditFacility.debt_id == debt.id))
    return boundary is None or ensure_utc(boundary) <= ensure_utc(cutoff)


def credit_visible(ledger_id, actor_account_id):
    allowed = select(CreditFacility.id).join(FinancialAccount, FinancialAccount.id == CreditFacility.account_id).where(
        CreditFacility.debt_id == Debt.id, account_scope(ledger_id, actor_account_id))
    return or_(Debt.source_type != "credit_facility", allowed.exists())


def credit_projection_available():
    lineage = select(AccountMovement.id.label("id"), AccountMovement.id.label("root_id"), literal(0).label("depth"))\
        .where(AccountMovement.reversal_of_id.is_(None)).cte(recursive=True)
    child = aliased(AccountMovement)
    lineage = lineage.union_all(select(child.id, lineage.c.root_id, lineage.c.depth + 1)
        .join(lineage, child.reversal_of_id == lineage.c.id))
    active_roots = select(lineage.c.root_id).group_by(lineage.c.root_id).having(func.max(lineage.c.depth) % 2 == 0)
    used_draw = select(func.coalesce(func.sum(CreditSettlementAllocation.amount_minor), 0)).where(
        active_allocation_condition(), CreditSettlementAllocation.draw_movement_id == AccountMovement.id).correlate(AccountMovement).scalar_subquery()
    used_credit = select(func.coalesce(func.sum(CreditSettlementAllocation.amount_minor), 0)).where(
        active_allocation_condition(), CreditSettlementAllocation.credit_movement_id == AccountMovement.id).correlate(AccountMovement).scalar_subquery()
    unknown = select(CreditFacility.id).join(FinancialAccount, FinancialAccount.id == CreditFacility.account_id).where(
        CreditFacility.debt_id == Debt.id, or_(FinancialAccount.balance_known.is_(False),
            select(AccountMovement.id).where(AccountMovement.account_id == FinancialAccount.id,
                AccountMovement.id.in_(active_roots), AccountMovement.home_amount_cents.is_(None),
                or_(-AccountMovement.amount_minor > used_draw, AccountMovement.amount_minor > used_credit)).exists()))
    return ~unknown.exists()


def credit_participant_allowed(debt, ledger_id, actor_account_id):
    db = object_session(debt)
    return db is not None and db.scalar(select(Debt.id).where(Debt.id == debt.id,
        credit_visible(ledger_id, actor_account_id))) is not None


def credit_home_balance(db: Session, debt: Debt, *, cutoff: datetime | None = None) -> tuple[int, int]:
    account = db.scalar(select(FinancialAccount).join(CreditFacility, CreditFacility.account_id == FinancialAccount.id)
        .where(CreditFacility.debt_id == debt.id))
    if account is None or not account.balance_known:
        raise AppError("credit_balance_unknown", "信用账户期初待核对，请打开资金账户查看已记录变动。", status_code=409)
    movements = active_credit_movements(db, account.id, cutoff=cutoff)
    used_draws, used_credits, _ = allocation_totals(db, [row.id for row in movements], cutoff=cutoff)
    remaining = sum(_remaining_home(draw, used_draws.get(draw.id, 0)) for draw in movements if draw.amount_minor < 0)
    spare = sum(_remaining_home(credit, used_credits.get(credit.id, 0)) for credit in movements if credit.amount_minor > 0)
    remaining = projection_sum_to_int(max(0, remaining - spare), label="credit.home_balance")
    voided = select(RepaymentVoid.id).where(RepaymentVoid.repayment_id == Repayment.id)
    if cutoff is not None:
        voided = voided.where(RepaymentVoid.created_at <= cutoff)
    paid_query = select(func.coalesce(func.sum(Repayment.amount_cents), 0)).where(Repayment.debt_id == debt.id, ~voided.exists())
    if cutoff is not None:
        paid_query = paid_query.where(Repayment.created_at <= cutoff)
    return remaining, projection_sum_to_int(db.scalar(paid_query), label="credit.home_paid")


def unallocated_credit_home(db: Session, account_id: int, *, cutoff: datetime | None = None) -> int:
    credits = [row for row in active_credit_movements(db, account_id, cutoff=cutoff) if row.amount_minor > 0]
    _, used, _ = allocation_totals(db, [row.id for row in credits], cutoff=cutoff)
    return sum(_remaining_home(credit, used.get(credit.id, 0)) for credit in credits)


def _remaining_home(movement: AccountMovement, used: int) -> int:
    original = abs(movement.amount_minor)
    if used >= original:
        return 0
    if movement.home_amount_cents is None:
        raise AppError("credit_balance_unknown", "信用账户原币金额已记录，本位币估值待补汇率。", status_code=409)
    basis = abs(movement.home_amount_cents)
    return basis - round_minor_ratio_half_up(basis * used, original, label="credit.remaining_home")
