"""One read owner for fulfillment, outstanding reservations and reminders."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseOffsetFact, RecurringItem, RecurringOccurrence
from app.money_contract import projection_sum_to_int
from app.schemas._recurring_occurrence import RecurringOccurrenceResponse
from app.services.spending_contract_service import clean_month, current_accounting_month, shift_month


def occurrence_period(month: str | None) -> date:
    return date.fromisoformat(f"{clean_month(month or current_accounting_month())}-01")


def eligible_payment_query(*, tenant_id: str):
    reversal = exists(select(ExpenseOffsetFact.id).where(
        ExpenseOffsetFact.tenant_id == Expense.tenant_id,
        ExpenseOffsetFact.expense_id == Expense.id,
        ExpenseOffsetFact.kind == "reversal",
        ExpenseOffsetFact.status == "active",
    )).correlate(Expense)
    return select(Expense).where(
        Expense.tenant_id == tenant_id,
        Expense.status == "confirmed",
        Expense.amount_cents > 0,
        ~reversal,
    )


def fulfilled_periods(
    db: Session, *, tenant_id: str, series_ids: list[int],
) -> dict[int, set[date]]:
    eligible_ids = eligible_payment_query(tenant_id=tenant_id).with_only_columns(Expense.id)
    rows = db.execute(select(RecurringOccurrence.series_id, RecurringOccurrence.period_start).where(
        RecurringOccurrence.tenant_id == tenant_id,
        RecurringOccurrence.series_id.in_(series_ids),
        RecurringOccurrence.expense_id.in_(eligible_ids),
    ))
    result: dict[int, set[date]] = {}
    for series_id, period in rows:
        result.setdefault(series_id, set()).add(period)
    return result


def next_due_date(item: RecurringItem, fulfilled: set[date]) -> date | None:
    anchor = item.next_expected_date
    if anchor is None or item.status != "active":
        return None
    period = anchor.replace(day=1)
    while period in fulfilled:
        period = occurrence_period(shift_month(period.strftime("%Y-%m"), 1))
    return period.replace(day=min(anchor.day, monthrange(period.year, period.month)[1]))


def next_due_dates(
    db: Session, *, tenant_id: str, items: list[RecurringItem],
) -> dict[int, date | None]:
    paid = fulfilled_periods(db, tenant_id=tenant_id, series_ids=[item.id for item in items])
    return {item.id: next_due_date(item, paid.get(item.id, set())) for item in items}


def occurrence_response(
    db: Session, *, item: RecurringItem, period: date,
) -> RecurringOccurrenceResponse:
    row = db.get(RecurringOccurrence, (item.tenant_id, item.id, period))
    expense = db.scalar(select(Expense).where(
        Expense.tenant_id == item.tenant_id,
        Expense.id == row.expense_id,
    )) if row is not None and row.expense_id is not None else None
    paid = fulfilled_periods(db, tenant_id=item.tenant_id, series_ids=[item.id]).get(item.id, set())
    valid = period in paid
    state = "fulfilled" if valid else "needs_review" if row and row.expense_id else "unfulfilled"
    baseline = projection_sum_to_int(item.baseline_amount_cents, label="recurring.occurrence_baseline")
    return RecurringOccurrenceResponse(
        series_public_id=item.public_id,
        period=period.strftime("%Y-%m"),
        series_row_version=item.row_version,
        row_version=row.row_version if row else 0,
        state=state,
        planned_amount_cents=baseline,
        reserved_amount_cents=baseline if item.status == "active" and not valid else 0,
        expense_public_id=expense.public_id if expense else None,
        expense_id=expense.id if expense else None,
        expense_row_version=expense.row_version if expense else None,
        paid_amount_cents=expense.amount_cents if expense and valid else None,
        next_due_date=next_due_date(item, paid),
    )


def total_outstanding_recurring_cents(
    db: Session, *, tenant_id: str, month: str,
) -> int:
    period = occurrence_period(month)
    items = list(db.scalars(select(RecurringItem).where(
        RecurringItem.tenant_id == tenant_id,
        RecurringItem.status == "active",
        RecurringItem.frequency == "monthly",
    )))
    paid = fulfilled_periods(db, tenant_id=tenant_id, series_ids=[item.id for item in items])
    return projection_sum_to_int(
        sum(item.baseline_amount_cents for item in items if period not in paid.get(item.id, set())),
        label="recurring.outstanding",
    )
