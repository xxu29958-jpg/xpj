"""Read-only CsvImportBatch lookups shared across _lifecycle / _csv_io /
_apply / _apply_lease / _idempotency.

Pulled out of _lifecycle to break the _csv_io ↔ _lifecycle import
cycle (5 lazy ``from ._lifecycle import get_csv_import_batch`` sites).
Pure DB query, no side effects — safe for any sibling to import at
module load.

Re-exported from ``_lifecycle`` so external callers
(``from app.services.csv_import_batch_service._lifecycle import
get_csv_import_batch``) keep working.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportEvent, CsvImportRow, Expense, ExpenseOffsetFact
from app.schemas import CsvImportBatchResponse, CsvImportRowResponse

__all__ = [
    "build_csv_import_batch_response", "get_csv_import_batch",
    "get_csv_import_batch_progress", "list_csv_import_batches", "list_imported_expenses",
]


@dataclass(frozen=True)
class CsvImportRowCounts:
    remaining_valid_rows: int = 0
    applied_rows: int = 0
    error_rows: int = 0
    matched_rows: int = 0
    review_rows: int = 0
    confirmed_offset_rows: int = 0

    @property
    def inserted_count(self) -> int:
        return self.applied_rows - self.confirmed_offset_rows


def list_imported_expenses(db: Session, *, tenant_id: str, expense_ids: list[int]) -> list[Expense]:
    """Current financial records referenced by the selected import page."""
    if not expense_ids:
        return []
    return list(db.scalars(ledger_scoped_select(Expense, tenant_id).where(Expense.id.in_(expense_ids))))


@dataclass(frozen=True)
class CsvImportBatchProgress:
    batch: CsvImportBatch
    row_counts: CsvImportRowCounts

    @property
    def display_status(self) -> tuple[str, str]:
        if self.row_counts.review_rows:
            return "待复核事件", "product-status--warning"
        if self.row_counts.remaining_valid_rows:
            return "待继续导入", "product-status--warning"
        if self.row_counts.error_rows:
            label = "部分导入，有错误" if self.row_counts.applied_rows else "有错误，未导入"
            return label, "product-status--warning"
        if self.row_counts.applied_rows or self.row_counts.matched_rows:
            return "已导入", "product-status--success"
        return "没有数据行", ""


@dataclass(frozen=True)
class CsvImportBatchPage:
    items: list[CsvImportBatchProgress]
    page: int
    page_size: int
    total: int
    total_pages: int


def get_csv_import_batch(
    db: Session, *, tenant_id: str, public_id: str
) -> CsvImportBatch:
    batch = db.scalar(
        ledger_scoped_select(CsvImportBatch, tenant_id).where(
            CsvImportBatch.public_id == public_id
        )
    )
    if batch is None:
        raise AppError("import_batch_not_found", "导入批次不存在。", status_code=404)
    return batch


def get_csv_import_row(db: Session, *, tenant_id: str, public_id: str, line_number: int) -> CsvImportRowResponse:
    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    row = db.scalar(ledger_scoped_select(CsvImportRow, tenant_id).where(
        CsvImportRow.batch_id == batch.id, CsvImportRow.line_number == line_number))
    if row is None:
        raise AppError("import_batch_not_found", "导入行不存在。", status_code=404)
    return build_csv_row_responses(db, tenant_id=tenant_id, rows=[row])[0]


def csv_row_status_filter(*, tenant_id: str, status: str):
    """One state interpretation for counts and filtered pages of aliased tasks."""
    if status not in {"review", "matched"}:
        return CsvImportRow.status == status
    resolved_review = (CsvImportRow.status == "review") & ledger_scoped_select(CsvImportEvent, tenant_id).where(
        CsvImportEvent.entry_kind == CsvImportRow.entry_kind,
        CsvImportEvent.source_event_public_id == CsvImportRow.source_event_public_id,
        or_((CsvImportEvent.entry_kind == "expense") & CsvImportEvent.expense_id.is_not(None),
            (CsvImportEvent.entry_kind == "offset") & CsvImportEvent.offset_id.is_not(None)),
    ).exists()
    if status == "matched":
        return (CsvImportRow.status == "matched") | resolved_review
    return (CsvImportRow.status == "review") & ~resolved_review


def _csv_import_row_counts(
    db: Session, *, tenant_id: str, batch_ids: list[int]
) -> dict[int, CsvImportRowCounts]:
    if not batch_ids:
        return {}
    rows = db.execute(
        ledger_scoped_select(CsvImportRow, tenant_id)
        .where(CsvImportRow.batch_id.in_(batch_ids))
        .with_only_columns(
            CsvImportRow.batch_id,
            func.count().filter(CsvImportRow.status.in_(("valid", "applying"))),
            func.count().filter(CsvImportRow.status == "applied"),
            func.count().filter(CsvImportRow.status.in_(("error", "insert_failed", "conflict"))),
            func.count().filter(csv_row_status_filter(tenant_id=tenant_id, status="matched")),
            func.count().filter(csv_row_status_filter(tenant_id=tenant_id, status="review")),
            func.count().filter((CsvImportRow.status == "applied") & (CsvImportRow.entry_kind == "offset")),
        )
        .group_by(CsvImportRow.batch_id)
    )
    return {
        int(batch_id): CsvImportRowCounts(*(int(value) for value in counts))
        for batch_id, *counts in rows
    }


def _csv_import_batch_counts(
    db: Session, *, tenant_id: str, batch_id: int,
) -> CsvImportRowCounts:
    return _csv_import_row_counts(
        db, tenant_id=tenant_id, batch_ids=[batch_id],
    ).get(batch_id, CsvImportRowCounts())


def _remaining_importable_rows(db: Session, batch: CsvImportBatch, tenant_id: str) -> int:
    return _csv_import_batch_counts(
        db, tenant_id=tenant_id, batch_id=batch.id,
    ).remaining_valid_rows


def build_csv_import_batch_response(
    db: Session, *, batch: CsvImportBatch,
) -> CsvImportBatchResponse:
    """Read current row results without updating the persisted batch cache or lease."""
    counts = _csv_import_batch_counts(db, tenant_id=batch.tenant_id, batch_id=batch.id)
    return CsvImportBatchResponse.model_validate(batch).model_copy(update={
        "applied_rows": counts.applied_rows,
        "inserted_count": counts.inserted_count,
        "error_rows": counts.error_rows,
        "matched_rows": counts.matched_rows,
        "review_rows": counts.review_rows,
        "confirmed_offset_rows": counts.confirmed_offset_rows,
    })


def _csv_fact_references(db: Session, *, tenant_id: str, rows: list[CsvImportRow],
                         source_ids: set[str], events: list[CsvImportEvent]
                         ) -> tuple[dict[int, Expense], dict[str, Expense], dict[int, str]]:
    """Load purchase and offset facts referenced by this page's source mappings."""
    expense_ids = {row.expense_id for row in rows if row.expense_id}
    expense_ids.update(event.expense_id for event in events if event.expense_id)
    expenses = list(db.scalars(ledger_scoped_select(Expense, tenant_id).where(
        or_(Expense.id.in_(expense_ids), Expense.public_id.in_(source_ids))))) if expense_ids or source_ids else []
    offset_ids = {event.offset_id for event in events if event.offset_id is not None}
    offsets = {offset.id: offset.public_id for offset in db.scalars(
        ledger_scoped_select(ExpenseOffsetFact, tenant_id).where(ExpenseOffsetFact.id.in_(offset_ids)))} if offset_ids else {}
    return {expense.id: expense for expense in expenses}, {expense.public_id: expense for expense in expenses}, offsets


def _csv_row_response(row: CsvImportRow, *, events: dict[tuple[str, str], CsvImportEvent],
                       expenses: dict[int, Expense], source_expenses: dict[str, Expense],
                       offsets: dict[int, str]) -> CsvImportRowResponse:
    """Project navigation and effective status without querying or changing the saved task."""
    event = events.get((row.entry_kind, row.source_event_public_id))
    root_event = events.get(("expense", row.source_root_public_id))
    expense_id = row.expense_id or (event.expense_id if event else None) or (root_event.expense_id if root_event else None)
    root = expenses.get(expense_id) or source_expenses.get(row.source_root_public_id)
    resolved = event is not None and (
        event.offset_id is not None if row.entry_kind == "offset" else event.expense_id is not None)
    return CsvImportRowResponse.model_validate(row).model_copy(update={
        "status": "matched" if row.status == "review" and resolved else row.status,
        "resolved_expense_id": root.id if root else None,
        "resolved_root_status": root.status if root else None,
        "resolved_root_row_version": root.row_version if root else None,
        "resolved_offset_public_id": offsets.get(event.offset_id) if event else None,
    })


def build_csv_row_responses(db: Session, *, tenant_id: str, rows: list[CsvImportRow]) -> list[CsvImportRowResponse]:
    """Resolve source navigation in bounded queries, without mutating task state."""
    source_ids = {value for row in rows for value in (row.source_event_public_id, row.source_root_public_id) if value}
    events = list(db.scalars(ledger_scoped_select(CsvImportEvent, tenant_id).where(
        CsvImportEvent.source_event_public_id.in_(source_ids)))) if source_ids else []
    by_source = {(event.entry_kind, event.source_event_public_id): event for event in events}
    expenses, source_expenses, offsets = _csv_fact_references(db, tenant_id=tenant_id, rows=rows,
        source_ids=source_ids, events=events)
    return [_csv_row_response(row, events=by_source, expenses=expenses, source_expenses=source_expenses,
        offsets=offsets) for row in rows]


def get_csv_import_batch_progress(
    db: Session, *, tenant_id: str, public_id: str
) -> CsvImportBatchProgress:
    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    return CsvImportBatchProgress(
        batch, _csv_import_batch_counts(db, tenant_id=tenant_id, batch_id=batch.id),
    )


def list_csv_import_batches(
    db: Session, *, tenant_id: str, page: int = 1, page_size: int = 20
) -> CsvImportBatchPage:
    page_size = min(max(page_size, 1), 100)
    query = ledger_scoped_select(CsvImportBatch, tenant_id)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(page, 1), total_pages)
    batches = list(db.scalars(
        query.order_by(CsvImportBatch.created_at.desc(), CsvImportBatch.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ))
    counts = _csv_import_row_counts(
        db, tenant_id=tenant_id, batch_ids=[batch.id for batch in batches]
    )
    return CsvImportBatchPage(
        items=[
            CsvImportBatchProgress(batch, counts.get(batch.id, CsvImportRowCounts()))
            for batch in batches
        ],
        page=page, page_size=page_size, total=total, total_pages=total_pages,
    )
