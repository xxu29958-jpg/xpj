"""Read or adapt confirmed stream entries, then project their recorded money once."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING

from app.models import Expense
from app.services.category_service import normalize_category
from app.services.money_projection_service import (
    CategorySpend,
    ProjectionGap,
    ordered_projection_gaps,
    project_recorded_amount,
    sum_projected_amounts,
)
from app.services.spending_contract_service import confirmed_stream_query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.schemas._expense_stream import ConfirmedExpenseStreamItem


@dataclass(frozen=True)
class ProjectedSpendingEntry:
    entry_id: int
    root_expense_id: int
    entry_kind: str
    stream_date: date | None
    category: str
    merchant: str | None
    home_currency_code: str | None
    amount_cents: int | None
    gap: ProjectionGap | None


@dataclass(frozen=True)
class SpendingPeriodProjection:
    entries: list[ProjectedSpendingEntry]
    undated_by_category: dict[str, int]

    @property
    def undated_expense_count(self) -> int:
        return sum(self.undated_by_category.values())


@dataclass(frozen=True)
class PurchaseSpending:
    expense_id: int
    month: str | None
    category: str
    amount_minor: int | None


def read_purchase_spending(db: Session, *, tenant_id: str, months: list[str], home: str,
                          as_of: date) -> list[PurchaseSpending]:
    """Envelope refunds restore the original purpose; reports retain their event dates.

    Reuse the confirmed stream's reversal, refund and recorded-FX semantics. This
    groups by the current purchase identity instead of moving a refund to an
    unrelated month's allocation. Unknown dates/amounts remain unknown.
    """
    from app.services.spending_contract_service import calendar_month_bounds
    stream = confirmed_stream_query(tenant_id=tenant_id)
    ranges = [calendar_month_bounds(month) for month in months]
    dates = or_(*((Expense.accounting_date >= start) & (Expense.accounting_date < end)
                  for start, end in ranges))
    query = select(stream, Expense.accounting_date.label("purchase_date"),
        Expense.category.label("purchase_category")).join(Expense, Expense.id == stream.c.root_expense_id).where(
            Expense.tenant_id == tenant_id, or_(dates, Expense.accounting_date.is_(None)),
            or_(stream.c.stream_date <= as_of, stream.c.stream_date.is_(None)))
    rows = list(db.execute(query))
    entries = _project_rows(db, tenant_id=tenant_id, home=home, rows=rows)
    grouped: dict[int, PurchaseSpending] = {}
    for row, entry in zip(rows, entries, strict=True):
        previous = grouped.get(entry.root_expense_id)
        amount = sum_projected_amounts((previous.amount_minor if previous else 0, entry.amount_cents),
                                       label="envelope.purchase")
        grouped[entry.root_expense_id] = PurchaseSpending(entry.root_expense_id,
            row.purchase_date.strftime("%Y-%m") if row.purchase_date else None,
            normalize_category(row.purchase_category), amount)
    return list(grouped.values())


def projected_category_spend(entries: Iterable[ProjectedSpendingEntry]) -> dict[str, CategorySpend]:
    spending: dict[str, CategorySpend] = {}
    for entry in entries:
        previous = spending.get(entry.category, CategorySpend())
        spending[entry.category] = CategorySpend(sum_projected_amounts(
            (previous.amount_cents, entry.amount_cents), label="spending.category"), previous.count + 1)
    return spending


def _project_rows(db, *, tenant_id, home, rows):
    entries = []
    rate_cache = {}
    for row in rows:
        gaps = set()
        amount = None if row.stream_amount_cents is None else project_recorded_amount(
            db, tenant_id=tenant_id, amount_minor=row.stream_amount_cents,
            source_currency=row.home_currency_code, home_currency=home, rate_date=row.stream_date,
            missing_rates=gaps, rate_cache=rate_cache)
        entries.append(ProjectedSpendingEntry(row.entry_id, row.root_expense_id, row.entry_kind, row.stream_date,
            normalize_category(row.category), row.merchant, row.home_currency_code, amount, next(iter(gaps), None)))
    return entries


def read_projected_entries(db: Session, *, tenant_id: str, ranges: Sequence[tuple[date, date]],
    timezone_name: str | None, home: str, tag: str | None = None,
) -> list[ProjectedSpendingEntry]:
    return read_spending_period(db, tenant_id=tenant_id, ranges=ranges,
        timezone_name=timezone_name, home=home, tag=tag).entries


def read_spending_period(db: Session, *, tenant_id: str, ranges: Sequence[tuple[date, date]],
    timezone_name: str | None, home: str, tag: str | None = None,
) -> SpendingPeriodProjection:
    """Read date gaps and dated contributions in one PostgreSQL statement snapshot."""
    if not ranges:
        return SpendingPeriodProjection([], {})
    stream = confirmed_stream_query(tenant_id=tenant_id, tag=tag, timezone_name=timezone_name)
    dated = stream.c.stream_amount_cents.is_not(None) & or_(*(
        (stream.c.stream_date >= start) & (stream.c.stream_date < end) for start, end in ranges))
    statement = select(stream).where(or_(dated,
        (stream.c.entry_kind == "expense") & stream.c.stream_date.is_(None)))
    rows, undated = [], {}
    for row in db.execute(statement):
        if row.stream_date is None:
            category = normalize_category(row.category)
            undated[category] = undated.get(category, 0) + 1
        else:
            rows.append(row)
    return SpendingPeriodProjection(_project_rows(db, tenant_id=tenant_id, home=home, rows=rows), undated)


def project_confirmed_items(db: Session, *, tenant_id: str, home: str,
    items: Iterable["ConfirmedExpenseStreamItem"],
) -> list[ProjectedSpendingEntry]:
    """Keep the original page, ordering and offset identity; do not query it again."""
    rows = []
    for item in items:
        source = item.offset or item.root
        source_home = item.offset.home_currency_code if item.offset is not None else item.root.home_currency
        amount = None if item.entry_kind == "expense" and item.root.amount_cents is None else item.stream_amount_cents
        rows.append(SimpleNamespace(entry_id=item.stream_sort_id, root_expense_id=item.root.id,
            entry_kind=item.entry_kind, stream_date=item.stream_date, category=source.category,
            merchant=item.root.merchant, home_currency_code=source_home,
            stream_amount_cents=amount))
    return _project_rows(db, tenant_id=tenant_id, home=home, rows=rows)


def entry_gaps(entries: Iterable[ProjectedSpendingEntry]) -> tuple[ProjectionGap, ...]:
    return ordered_projection_gaps(entry.gap for entry in entries if entry.gap is not None)
