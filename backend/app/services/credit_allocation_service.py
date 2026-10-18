"""Match actual native credit/debit movements, including prepayments used by a later purchase."""
from sqlalchemy import func, select

from app.models import AccountMovement, CreditSettlementAllocation
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


def unallocated_credit_minor(db, account_id):
    credits = [row for row in active_credit_movements(db, account_id) if row.amount_minor > 0]
    used = int(db.scalar(select(func.coalesce(func.sum(CreditSettlementAllocation.amount_minor), 0)).where(
        active_allocation_condition(), CreditSettlementAllocation.credit_movement_id.in_([row.id for row in credits]))))
    return sum(row.amount_minor for row in credits) - used


def allocate_credit(db, account):
    """Caller holds the account lock. Allocation describes funding, never creates an Expense."""
    db.flush()
    rows = sorted(active_credit_movements(db, account.id), key=lambda row: (row.occurred_on, row.id))
    debits = [row for row in rows if row.amount_minor < 0]
    credits = [row for row in rows if row.amount_minor > 0]
    used_debits = dict(db.execute(select(CreditSettlementAllocation.draw_movement_id,
        func.sum(CreditSettlementAllocation.amount_minor)).where(active_allocation_condition(), CreditSettlementAllocation.draw_movement_id.in_([r.id for r in debits]))
        .group_by(CreditSettlementAllocation.draw_movement_id)).all())
    used_credits = dict(db.execute(select(CreditSettlementAllocation.credit_movement_id,
        func.sum(CreditSettlementAllocation.amount_minor)).where(active_allocation_condition(), CreditSettlementAllocation.credit_movement_id.in_([r.id for r in credits]))
        .group_by(CreditSettlementAllocation.credit_movement_id)).all())
    used_pairs = {(credit_id, draw_id): int(amount) for credit_id, draw_id, amount in db.execute(select(
        CreditSettlementAllocation.credit_movement_id, CreditSettlementAllocation.draw_movement_id,
        func.sum(CreditSettlementAllocation.amount_minor)).where(active_allocation_condition(),
        CreditSettlementAllocation.credit_movement_id.in_([r.id for r in credits]))
        .group_by(CreditSettlementAllocation.credit_movement_id, CreditSettlementAllocation.draw_movement_id))}
    for credit in credits:
        available = credit.amount_minor - int(used_credits.get(credit.id, 0))
        choices = credit.settlement_targets or {}
        for debit in sorted(debits, key=lambda row: (str(row.id) not in choices, row.occurred_on, row.id)):
            used = int(used_debits.get(debit.id, 0))
            intended = max(0, choices.get(str(debit.id), 0) - used_pairs.get((credit.id, debit.id), 0))
            # Existing reviewed targets survive a correction/undo. Only a later actual draw can consume spare prepayment.
            take = min(available, -debit.amount_minor - used,
                intended if str(debit.id) in choices else available if debit.id > credit.id else 0)
            if take <= 0:
                continue
            released = None
            if debit.home_amount_cents is not None:
                basis = -debit.home_amount_cents
                before = round_minor_ratio_half_up(basis * used, -debit.amount_minor, label="credit.allocated_basis")
                after = round_minor_ratio_half_up(basis * (used + take), -debit.amount_minor, label="credit.allocated_basis")
                released = after - before
            db.add(CreditSettlementAllocation(credit_movement_id=credit.id, draw_movement_id=debit.id,
                repayment_id=credit.repayment_id, amount_minor=take, home_amount_cents=released))
            used_debits[debit.id] = used + take
            available -= take
    db.flush()
