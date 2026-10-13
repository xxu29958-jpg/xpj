"""Existing payment eligibility shared by recurring observations and fulfillment."""

from sqlalchemy import case, exists, select

from app.models import Expense, ExpenseOffsetFact


def _ineligible_payment_conditions():
    reversal = exists(select(ExpenseOffsetFact.id).where(
        ExpenseOffsetFact.tenant_id == Expense.tenant_id,
        ExpenseOffsetFact.expense_id == Expense.id,
        ExpenseOffsetFact.kind == "reversal",
        ExpenseOffsetFact.status == "active",
    )).correlate(Expense)
    return (
        (Expense.status != "confirmed", "not_confirmed"),
        (Expense.amount_cents < 0, "negative_amount"),
        (reversal, "reversed"),
    )


def eligible_payment_query(*, tenant_ids: list[str]):
    return select(Expense).where(
        Expense.tenant_id.in_(tenant_ids),
        *(~condition for condition, _ in _ineligible_payment_conditions()),
    )


def payment_review_reason_expression():
    """Explain the same eligibility rule without changing the linked payment."""
    return case(*_ineligible_payment_conditions(), else_=None)
