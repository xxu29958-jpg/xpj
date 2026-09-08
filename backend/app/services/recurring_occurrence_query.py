"""One read owner for fulfillment, outstanding reservations and reminders."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, ExpenseOffsetFact, RecurringItem, RecurringOccurrence
from app.money_contract import projection_sum_to_int
from app.schemas._recurring_occurrence import RecurringOccurrenceResponse
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.recurring_service import recurring_monthly_total
from app.services.spending_contract_service import (
    clean_month,
    current_accounting_month,
    month_bounds_utc,
    shift_month,
    stat_time_expr,
)


def occurrence_period(month: str | None) -> date:
    return date.fromisoformat(f"{clean_month(month or current_accounting_month())}-01")


def get_occurrence(db: Session, *, tenant_id: str, series_id: int, period: date) -> RecurringOccurrence | None:
    return db.scalar(select(RecurringOccurrence).where(
        RecurringOccurrence.tenant_id == tenant_id,
        RecurringOccurrence.series_id == series_id,
        RecurringOccurrence.period_start == period,
    ).execution_options(populate_existing=True))


def eligible_payment_query(*, tenant_id: str):
    return _eligible_payments_for_ledgers([tenant_id])


def _eligible_payments_for_ledgers(tenant_ids: list[str]):
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


def find_recurring_payments(db: Session, *, tenant_id: str, month: str | None, query: str) -> list[Expense]:
    statement = eligible_payment_query(tenant_id=tenant_id)
    if month:
        start, end = month_bounds_utc(month)
        statement = statement.where(stat_time_expr() >= start, stat_time_expr() < end)
    if query:
        statement = statement.where(or_(
            Expense.merchant.contains(query, autoescape=True), Expense.note.contains(query, autoescape=True),
        ))
    return list(db.scalars(statement.order_by(stat_time_expr().desc(), Expense.id.desc()).limit(101)))


def next_due_dates_for_ledgers(db: Session, *, tenant_ids: list[str]) -> list[date]:
    items = list(db.scalars(select(RecurringItem).where(
        RecurringItem.tenant_id.in_(tenant_ids), RecurringItem.status == "active",
    )))
    eligible_ids = _eligible_payments_for_ledgers(tenant_ids).with_only_columns(Expense.id)
    rows = db.execute(select(RecurringOccurrence.series_id, RecurringOccurrence.period_start).where(
        RecurringOccurrence.tenant_id.in_(tenant_ids),
        RecurringOccurrence.expense_id.in_(eligible_ids),
    ))
    fulfilled: dict[int, set[date]] = {}
    for series_id, period in rows:
        fulfilled.setdefault(series_id, set()).add(period)
    return [day for item in items if (day := next_due_date(item, fulfilled.get(item.id, set()))) is not None]


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
    row = get_occurrence(db, tenant_id=item.tenant_id, series_id=item.id, period=period)
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
        home_currency_code=item.home_currency_code,
        planned_amount_cents=baseline,
        reserved_amount_cents=baseline if item.status == "active" and not valid else 0,
        **_occurrence_payment_fields(expense, valid=valid),
        next_due_date=next_due_date(item, paid),
    )


def _occurrence_payment_fields(expense: Expense | None, *, valid: bool) -> dict:
    paid = expense if valid else None
    return {
        "expense_public_id": expense.public_id if expense else None,
        "expense_id": expense.id if expense else None,
        "expense_row_version": expense.row_version if expense else None,
        "paid_amount_cents": paid.amount_cents if paid else None,
        "paid_home_currency_code": paid.home_currency_code if paid else None,
    }


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
    total = recurring_monthly_total(db, tenant_id=tenant_id,
        items=[item for item in items if period not in paid.get(item.id, set())],
        home_currency_code=require_runtime_home_currency_code(db), month=period.strftime("%Y-%m"))
    if total is None:
        raise AppError("recurring_projection_unavailable", "固定支出的币种或汇率待补充，暂时无法计算预算预留。", status_code=409)
    return total
