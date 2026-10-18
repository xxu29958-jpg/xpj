"""Match actual native credit/debit movements, including prepayments used by a later purchase."""
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import AccountMovement, CreditSettlementAllocation, FinancialAccount
from app.money_contract import round_minor_ratio_half_up


def active_credit_movements(db, account_id, *, cutoff=None):
    """A reversal cancels its source; reversing that correction restores the original identity."""
    query = select(AccountMovement).where(AccountMovement.account_id == account_id)
    if cutoff is not None:
        query = query.where(AccountMovement.created_at <= cutoff)
    roots, lineage, active = {}, {}, set()
    for row in db.scalars(query.order_by(AccountMovement.id)):
        if row.reversal_of_id is None:
            roots[row.id], lineage[row.id] = row, row.id
            active.add(row.id)
        else:
            root = lineage[row.reversal_of_id]
            lineage[row.id] = root
            active.symmetric_difference_update({root})
    return [roots[identifier] for identifier in active]


def active_allocation_condition(*, cutoff=None):
    if cutoff is None:
        return CreditSettlementAllocation.invalidated_by_movement_id.is_(None)
    return ~select(AccountMovement.id).where(
        AccountMovement.id == CreditSettlementAllocation.invalidated_by_movement_id,
        AccountMovement.created_at <= cutoff).exists()


def allocation_totals(db: Session, movement_ids: list[int], *, cutoff: datetime | None = None
                      ) -> tuple[dict[int, int], dict[int, int], dict[tuple[int, int], int]]:
    """Read the same active allocation facts once for both sides of a credit account."""
    query = select(CreditSettlementAllocation.credit_movement_id, CreditSettlementAllocation.draw_movement_id,
        func.sum(CreditSettlementAllocation.amount_minor)).where(active_allocation_condition(cutoff=cutoff),
        or_(CreditSettlementAllocation.credit_movement_id.in_(movement_ids),
            CreditSettlementAllocation.draw_movement_id.in_(movement_ids)))
    if cutoff is not None:
        query = query.where(CreditSettlementAllocation.created_at <= cutoff)
    debits, credits, pairs = {}, {}, {}
    for credit_id, draw_id, amount in db.execute(query.group_by(
            CreditSettlementAllocation.credit_movement_id, CreditSettlementAllocation.draw_movement_id)):
        amount = int(amount)
        debits[draw_id] = debits.get(draw_id, 0) + amount
        credits[credit_id] = credits.get(credit_id, 0) + amount
        pairs[(credit_id, draw_id)] = amount
    return debits, credits, pairs


def unallocated_credit_minor(db, account_id):
    credits = [row for row in active_credit_movements(db, account_id) if row.amount_minor > 0]
    used = int(db.scalar(select(func.coalesce(func.sum(CreditSettlementAllocation.amount_minor), 0)).where(
        active_allocation_condition(), CreditSettlementAllocation.credit_movement_id.in_([row.id for row in credits]))))
    return sum(row.amount_minor for row in credits) - used


def allocate_credit(db: Session, account: FinancialAccount) -> None:
    """Caller holds the account lock. Allocation describes funding, never creates an Expense."""
    db.flush()
    rows = sorted(active_credit_movements(db, account.id), key=lambda row: (row.occurred_on, row.id))
    debits = [row for row in rows if row.amount_minor < 0]
    credits = [row for row in rows if row.amount_minor > 0]
    used_debits, used_credits, used_pairs = allocation_totals(db, [row.id for row in rows])
    for credit in credits:
        available = credit.amount_minor - int(used_credits.get(credit.id, 0))
        choices = credit.settlement_targets or {}
        for debit in sorted(debits, key=lambda row: (str(row.id) not in choices, row.occurred_on, row.id)):
            used = int(used_debits.get(debit.id, 0))
            # Existing reviewed targets survive a correction/undo. Only a later actual draw can consume spare prepayment.
            intended = _remaining_target(credit, debit, used_pairs)
            take = min(available, -debit.amount_minor - used, intended)
            if take <= 0:
                continue
            db.add(CreditSettlementAllocation(credit_movement_id=credit.id, draw_movement_id=debit.id,
                repayment_id=credit.repayment_id, amount_minor=take, home_amount_cents=_released_basis(debit, used, take)))
            used_debits[debit.id] = used + take
            available -= take
    db.flush()


def _remaining_target(credit: AccountMovement, debit: AccountMovement, used_pairs: dict[tuple[int, int], int]) -> int:
    choices = credit.settlement_targets or {}
    if str(debit.id) in choices:
        return max(0, choices[str(debit.id)] - used_pairs.get((credit.id, debit.id), 0))
    return credit.amount_minor if debit.id > credit.id else 0


def _released_basis(debit: AccountMovement, used: int, take: int) -> int | None:
    if debit.home_amount_cents is None:
        return None
    basis = -debit.home_amount_cents
    before = round_minor_ratio_half_up(basis * used, -debit.amount_minor, label="credit.allocated_basis")
    after = round_minor_ratio_half_up(basis * (used + take), -debit.amount_minor, label="credit.allocated_basis")
    return after - before
