"""Read fees through their original Expense, funding and settlement facts."""
from collections import defaultdict

from sqlalchemy import select

from app.models import (
    AccountMovement,
    CreditFeeObligation,
    Expense,
    ExpenseFunding,
    ExpenseOffsetFact,
    InstallmentPeriod,
)
from app.schemas.credit_fee import CreditFeeView
from app.services.credit_allocation_service import allocation_totals
from app.services.expense_offset_summary import expense_financial_summary


def fee_movement_ids(account_id):
    return select(AccountMovement.id).join(ExpenseFunding, ExpenseFunding.id == AccountMovement.funding_id).join(
        CreditFeeObligation, CreditFeeObligation.expense_id == ExpenseFunding.expense_id).where(AccountMovement.account_id == account_id)


def fee_sources(db, account_ids):
    return list(db.execute(select(CreditFeeObligation, Expense, AccountMovement, InstallmentPeriod.public_id)
        .join(Expense, Expense.id == CreditFeeObligation.expense_id)
        .join(ExpenseFunding, ExpenseFunding.expense_id == Expense.id)
        .join(AccountMovement, AccountMovement.funding_id == ExpenseFunding.id)
        .outerjoin(InstallmentPeriod, InstallmentPeriod.id == CreditFeeObligation.period_id)
        .where(CreditFeeObligation.account_id.in_(account_ids), ExpenseFunding.account_id == CreditFeeObligation.account_id,
               Expense.tenant_id == ExpenseFunding.tenant_id, ExpenseFunding.voided_at.is_(None))))


def fee_views(db, account_id):
    rows = fee_sources(db, [account_id])
    used, _, _ = allocation_totals(db, [movement.id for _, _, movement, _ in rows])
    return [CreditFeeView(expense_id=expense.id, note=expense.note or expense.merchant or "已发生费用",
        occurred_on=expense.accounting_date, original_minor=-movement.amount_minor,
        remaining_minor=-movement.amount_minor - used.get(movement.id, 0), period_public_id=period)
        for _, expense, movement, period in rows]


def fee_period_totals(db, period_ids):
    """Return retained incurred fees and paid fees; refunds do not count as payments."""
    account_ids = db.scalars(select(CreditFeeObligation.account_id).where(
        CreditFeeObligation.period_id.in_(period_ids)).distinct()).all()
    rows = [row for row in fee_sources(db, account_ids) if row[0].period_id in period_ids]
    used, _, _ = allocation_totals(db, [movement.id for _, _, movement, _ in rows])
    offsets = defaultdict(list)
    for row in db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id.in_([e.id for _, e, _, _ in rows]),
            ExpenseOffsetFact.status == "active")):
        offsets[row.expense_id].append(row)
    totals = dict.fromkeys(period_ids, (0, 0))
    for obligation, expense, movement, _ in rows:
        net = expense_financial_summary(expense, offsets[expense.id]).remaining_refundable_original_minor
        unpaid = -movement.amount_minor - used.get(movement.id, 0)
        incurred, paid = totals[obligation.period_id]
        totals[obligation.period_id] = (incurred + net, paid + max(0, net - unpaid))
    return totals
