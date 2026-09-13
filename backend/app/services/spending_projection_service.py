"""Read or adapt confirmed stream entries, then project their recorded money once."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.services.category_service import normalize_category
from app.services.money_projection_service import (
    ProjectionGap,
    ordered_projection_gaps,
    project_recorded_amount,
)
from app.services.spending_contract_service import accounting_zone, confirmed_stream_query

if TYPE_CHECKING:
    from app.schemas._expense_stream import ConfirmedExpenseStreamItem


@dataclass(frozen=True)
class ProjectedSpendingEntry:
    entry_id: int
    root_expense_id: int
    entry_kind: str
    stream_date: date
    category: str
    merchant: str | None
    home_currency_code: str | None
    amount_cents: int | None
    gap: ProjectionGap | None


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


def read_projected_entries(db: Session, *, tenant_id: str, ranges: Sequence[tuple[datetime, datetime]],
    timezone_name: str | None, home: str, tag: str | None = None,
) -> list[ProjectedSpendingEntry]:
    zone = accounting_zone(timezone_name)
    dates = [(start.astimezone(zone).date(), end.astimezone(zone).date()) for start, end in ranges]
    if not dates:
        return []
    stream = confirmed_stream_query(tenant_id=tenant_id, tag=tag, timezone_name=timezone_name, amount_required=True)
    statement = select(stream).where(or_(*(
        (stream.c.stream_date >= start) & (stream.c.stream_date < end) for start, end in dates)))
    return _project_rows(db, tenant_id=tenant_id, home=home, rows=db.execute(statement))


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
