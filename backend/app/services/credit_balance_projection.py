"""The existing Debt reads its revolving obligation from the native funds facts."""
from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.orm import aliased, object_session

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
from app.services.credit_allocation_service import active_allocation_condition, active_credit_movements
from app.services.time_service import ensure_utc


def uses_credit_at(db, debt, cutoff):
    if debt.source_type != "credit_facility":
        return False
    boundary = db.scalar(select(CreditFacility.adopted_at).where(CreditFacility.debt_id == debt.id))
    return boundary is None or ensure_utc(boundary) <= ensure_utc(cutoff)


def credit_visible(ledger_id, actor_account_id):
    allowed = select(CreditFacility.id).join(FinancialAccount, FinancialAccount.id == CreditFacility.account_id).where(
        CreditFacility.debt_id == Debt.id,
        or_(FinancialAccount.owner_account_id == actor_account_id,
            and_(FinancialAccount.tenant_id == ledger_id, FinancialAccount.visibility == "ledger")))
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


def credit_home_balance(db, debt, *, cutoff=None):
    account = db.scalar(select(FinancialAccount).join(CreditFacility, CreditFacility.account_id == FinancialAccount.id)
        .where(CreditFacility.debt_id == debt.id))
    if account is None or not account.balance_known:
        raise AppError("credit_balance_unknown", "信用账户期初待核对，请打开资金账户查看已记录变动。", status_code=409)
    remaining = 0
    for debit in active_credit_movements(db, account.id, cutoff=cutoff):
        if debit.amount_minor >= 0:
            continue
        allocated = select(func.coalesce(func.sum(CreditSettlementAllocation.amount_minor), 0)).where(
            active_allocation_condition(cutoff=cutoff), CreditSettlementAllocation.draw_movement_id == debit.id)
        if cutoff is not None:
            allocated = allocated.where(CreditSettlementAllocation.created_at <= cutoff)
        native = -debit.amount_minor - int(db.scalar(allocated))
        if native > 0:
            if debit.home_amount_cents is None:
                raise AppError("credit_balance_unknown", "信用账户原币金额已记录，本位币估值待补汇率。", status_code=409)
            remaining += -debit.home_amount_cents - round_minor_ratio_half_up(
                -debit.home_amount_cents * (-debit.amount_minor - native), -debit.amount_minor, label="credit.home_released")
    remaining = projection_sum_to_int(max(0, remaining - unallocated_credit_home(db, account.id, cutoff=cutoff)), label="credit.home_balance")
    voided = select(RepaymentVoid.id).where(RepaymentVoid.repayment_id == Repayment.id)
    if cutoff is not None:
        voided = voided.where(RepaymentVoid.created_at <= cutoff)
    paid_query = select(func.coalesce(func.sum(Repayment.amount_cents), 0)).where(Repayment.debt_id == debt.id, ~voided.exists())
    if cutoff is not None:
        paid_query = paid_query.where(Repayment.created_at <= cutoff)
    return remaining, projection_sum_to_int(db.scalar(paid_query), label="credit.home_paid")


def unallocated_credit_home(db, account_id, *, cutoff=None):
    total = 0
    for credit in active_credit_movements(db, account_id, cutoff=cutoff):
        if credit.amount_minor <= 0:
            continue
        allocated = select(func.coalesce(func.sum(CreditSettlementAllocation.amount_minor), 0)).where(
            active_allocation_condition(cutoff=cutoff), CreditSettlementAllocation.credit_movement_id == credit.id)
        if cutoff is not None:
            allocated = allocated.where(CreditSettlementAllocation.created_at <= cutoff)
        used = int(db.scalar(allocated))
        if used == credit.amount_minor:
            continue
        if credit.home_amount_cents is None:
            raise AppError("credit_balance_unknown", "已记录抵扣余额，本位币估值待补汇率。", status_code=409)
        total += credit.home_amount_cents - round_minor_ratio_half_up(
            credit.home_amount_cents * used, credit.amount_minor, label="credit.unallocated_home")
    return total
