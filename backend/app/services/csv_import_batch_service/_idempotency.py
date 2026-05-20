"""CSV import idempotency: dedupe by (batch_public_id, line_number).

Each apply attempt computes a row-level idempotency key and, on
``IntegrityError`` from the bulk insert, walks the claimed rows
checking whether each conflict corresponds to an existing Expense
inserted by a prior apply. If every conflicted row matches, the apply
succeeds with ``inserted_count=0`` — the user safely retried a partial
apply.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow, Expense
from app.schemas import CsvImportApplyResponse, CsvImportBatchResponse
from app.services.csv_import_batch_service._apply_lease import (
    _finalize_csv_import_apply_success,
)
from app.services.time_service import now_utc


def _csv_import_row_idempotency_key(batch: CsvImportBatch, row: CsvImportRow) -> str:
    return f"csv-import:{batch.public_id}:{row.line_number}"


def _existing_csv_import_expense_id(
    db: Session,
    *,
    tenant_id: str,
    idempotency_key: str,
) -> int | None:
    value = db.scalar(
        select(Expense.id)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.draft_idempotency_key == idempotency_key)
        .limit(1)
    )
    return int(value) if value is not None else None


def _resolve_csv_import_idempotency_conflict(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    row_ids: list[int],
    apply_token: str,
) -> CsvImportApplyResponse | None:
    # Lazy import to avoid an idempotency ↔ lifecycle cycle.
    from app.services.csv_import_batch_service._lifecycle import get_csv_import_batch

    if not row_ids:
        return None
    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    rows = list(
        db.scalars(
            ledger_scoped_select(CsvImportRow, tenant_id)
            .where(CsvImportRow.batch_id == batch.id)
            .where(CsvImportRow.id.in_(row_ids))
            .where(CsvImportRow.status == "applying")
            .where(CsvImportRow.apply_token == apply_token)
            .order_by(CsvImportRow.line_number.asc())
        )
    )
    if len(rows) != len(set(row_ids)):
        return None
    now = now_utc()
    for row in rows:
        existing_expense_id = _existing_csv_import_expense_id(
            db,
            tenant_id=tenant_id,
            idempotency_key=_csv_import_row_idempotency_key(batch, row),
        )
        if existing_expense_id is None:
            return None
        row.status = "applied"
        row.apply_token = None
        row.expense_id = existing_expense_id
        row.updated_at = now
    db.flush()
    remaining_rows = _finalize_csv_import_apply_success(
        db,
        batch=batch,
        tenant_id=tenant_id,
        public_id=public_id,
        apply_token=apply_token,
        now=now,
    )
    db.commit()
    db.refresh(batch)
    return CsvImportApplyResponse(
        batch=CsvImportBatchResponse.model_validate(batch),
        inserted_count=0,
        remaining_valid_rows=remaining_rows,
    )
