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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow, Expense
from app.schemas import CsvImportBatchResponse

__all__ = [
    "build_csv_import_batch_response", "get_csv_import_batch",
    "get_csv_import_batch_progress", "list_csv_import_batches", "list_imported_expenses",
]


@dataclass(frozen=True)
class CsvImportRowCounts:
    remaining_valid_rows: int = 0
    applied_rows: int = 0
    error_rows: int = 0


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
        if self.row_counts.remaining_valid_rows:
            return "待继续导入", "product-status--warning"
        if self.row_counts.error_rows:
            label = "部分导入，有错误" if self.row_counts.applied_rows else "有错误，未导入"
            return label, "product-status--warning"
        if self.row_counts.applied_rows:
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
            func.count().filter(CsvImportRow.status.in_(("error", "insert_failed"))),
        )
        .group_by(CsvImportRow.batch_id)
    )
    return {
        int(batch_id): CsvImportRowCounts(int(remaining), int(applied), int(errors))
        for batch_id, remaining, applied, errors in rows
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
        "inserted_count": counts.applied_rows,
        "error_rows": counts.error_rows,
    })


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
