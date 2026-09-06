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
from app.models import CsvImportBatch, CsvImportRow

__all__ = ["get_csv_import_batch", "get_csv_import_batch_progress", "list_csv_import_batches"]


@dataclass(frozen=True)
class CsvImportBatchProgress:
    batch: CsvImportBatch
    remaining_valid_rows: int

    @property
    def display_status(self) -> tuple[str, str]:
        if self.remaining_valid_rows:
            return "待继续导入", "product-status--warning"
        if self.batch.error_rows:
            label = "部分导入，有错误" if self.batch.applied_rows else "有错误，未导入"
            return label, "product-status--warning"
        if self.batch.applied_rows:
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


def _remaining_csv_import_row_counts(
    db: Session, *, tenant_id: str, batch_ids: list[int]
) -> dict[int, int]:
    if not batch_ids:
        return {}
    rows = db.execute(
        ledger_scoped_select(CsvImportRow, tenant_id)
        .where(CsvImportRow.batch_id.in_(batch_ids))
        .where(CsvImportRow.status.in_(("valid", "applying")))
        .with_only_columns(CsvImportRow.batch_id, func.count())
        .group_by(CsvImportRow.batch_id)
    )
    return {int(batch_id): int(count) for batch_id, count in rows}


def _remaining_importable_rows(db: Session, batch: CsvImportBatch, tenant_id: str) -> int:
    return _remaining_csv_import_row_counts(
        db, tenant_id=tenant_id, batch_ids=[batch.id]
    ).get(batch.id, 0)


def get_csv_import_batch_progress(
    db: Session, *, tenant_id: str, public_id: str
) -> CsvImportBatchProgress:
    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    return CsvImportBatchProgress(batch, _remaining_importable_rows(db, batch, tenant_id))


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
    remaining = _remaining_csv_import_row_counts(
        db, tenant_id=tenant_id, batch_ids=[batch.id for batch in batches]
    )
    return CsvImportBatchPage(
        items=[CsvImportBatchProgress(batch, remaining.get(batch.id, 0)) for batch in batches],
        page=page, page_size=page_size, total=total, total_pages=total_pages,
    )
