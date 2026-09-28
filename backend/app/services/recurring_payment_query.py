"""Existing payment eligibility shared by recurring observations and fulfillment."""

from sqlalchemy import exists, select

from app.models import Expense, ExpenseOffsetFact


def eligible_payment_query(*, tenant_ids: list[str]):
    reversal = exists(select(ExpenseOffsetFact.id).where(
        ExpenseOffsetFact.tenant_id == Expense.tenant_id,
        ExpenseOffsetFact.expense_id == Expense.id,
        ExpenseOffsetFact.kind == "reversal",
        ExpenseOffsetFact.status == "active",
    )).correlate(Expense)
    return select(Expense).where(
        Expense.tenant_id.in_(tenant_ids),
        Expense.status == "confirmed",
        Expense.amount_cents >= 0,
        ~reversal,
    )
