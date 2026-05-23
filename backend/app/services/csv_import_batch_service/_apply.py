"""The CSV import apply orchestrator.

Top-level state-machine driver. Each call:

1. Claims a batch-level lease (``_claim_apply_lease``).
2. Recovers stale row-level leases from a prior crashed apply.
3. Claims a row-level lease over ``batch_size`` ``valid`` rows.
4. Inserts an Expense per row (or marks the row ``insert_failed`` /
   ``applied`` based on idempotency).
5. Finalises the batch (``_finalize_csv_import_apply_success``).
6. On AppError / IntegrityError / unexpected Exception: rolls back +
   releases the lease + marks the batch failed if needed.

State preconditions for each helper are documented in their own
modules. The three-branch exception ladder
(``AppError`` / ``IntegrityError`` / ``Exception``) is preserved
byte-for-byte from the pre-split implementation — changing it requires
a deliberate state-machine review.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportRow, Expense
from app.schemas import CsvImportApplyResponse, CsvImportBatchResponse
from app.services.csv_import_batch_service._apply_lease import (
    _claim_apply_lease,
    _finalize_csv_import_apply_success,
    _mark_csv_import_apply_failed,
    _release_csv_import_apply_lease,
)
from app.services.csv_import_batch_service._common import ROW_APPLY_LEASE_MINUTES
from app.services.csv_import_batch_service._idempotency import (
    _csv_import_row_idempotency_key,
    _existing_csv_import_expense_id,
    _resolve_csv_import_idempotency_conflict,
)
from app.services.csv_import_batch_service._queries import get_csv_import_batch
from app.services.csv_import_batch_service._row_claim import (
    _applying_row_count,
    _claim_csv_import_rows,
    _recover_stale_csv_import_rows,
    _refresh_claimed_csv_import_row,
    _reset_claimed_csv_import_rows,
)
from app.services.exchange_rate_service import apply_currency_payload, home_currency_code
from app.services.import_service import DEFAULT_SOURCE
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import now_utc


def apply_csv_import_batch(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    batch_size: int,
) -> CsvImportApplyResponse:
    apply_token = str(uuid4())
    batch = _claim_apply_lease(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        apply_token=apply_token,
    )
    inserted = 0
    claimed_row_ids: list[int] = []
    try:
        _recover_stale_csv_import_rows(
            db,
            tenant_id=tenant_id,
            batch_id=batch.id,
            stale_before=now_utc() - timedelta(minutes=ROW_APPLY_LEASE_MINUTES),
        )
        claimed_row_ids = _claim_csv_import_rows(
            db,
            tenant_id=tenant_id,
            batch_id=batch.id,
            batch_size=batch_size,
            apply_token=apply_token,
        )
        batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
        if not claimed_row_ids and _applying_row_count(db, batch, tenant_id) > 0:
            raise AppError("invalid_request", "导入批次正在应用中，请稍后重试。", status_code=409)
        rows = list(
            db.scalars(
                ledger_scoped_select(CsvImportRow, tenant_id)
                .where(CsvImportRow.batch_id == batch.id)
                .where(CsvImportRow.id.in_(claimed_row_ids))
                .where(CsvImportRow.status == "applying")
                .where(CsvImportRow.apply_token == apply_token)
                .order_by(CsvImportRow.line_number.asc())
            )
        )
        now = now_utc()
        created: list[tuple[CsvImportRow, Expense]] = []
        for row in rows:
            if not _refresh_claimed_csv_import_row(
                db,
                tenant_id=tenant_id,
                row_id=row.id,
                apply_token=apply_token,
                now=now,
            ):
                continue
            if row.amount_cents is None and row.original_amount_minor is None:
                row.status = "insert_failed"
                row.apply_token = None
                row.error_code = "amount_required"
                row.error_message = "缺少有效金额。"
                row.updated_at = now
                continue
            idempotency_key = _csv_import_row_idempotency_key(batch, row)
            existing_expense_id = _existing_csv_import_expense_id(
                db,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
            )
            if existing_expense_id is not None:
                row.status = "applied"
                row.apply_token = None
                row.expense_id = existing_expense_id
                row.updated_at = now
                continue
            expense = Expense(
                tenant_id=tenant_id,
                amount_cents=None,
                draft_idempotency_key=idempotency_key,
                merchant=row.merchant or None,
                category=row.category or "其他",
                note=row.note or "",
                source=row.source or DEFAULT_SOURCE,
                tags=normalize_tags(row.tags),
                expense_time=row.expense_time,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            apply_currency_payload(
                db,
                tenant_id=tenant_id,
                expense=expense,
                payload=row,
                amount_was_explicit=row.original_currency_code == home_currency_code()
                and row.amount_cents is not None,
            )
            db.add(expense)
            created.append((row, expense))
        db.flush()
        for row, expense in created:
            sync_expense_tags(db, expense)
            row.status = "applied"
            row.apply_token = None
            row.expense_id = expense.id
            row.updated_at = now
            inserted += 1

        db.flush()
        remaining_rows = _finalize_csv_import_apply_success(
            db,
            batch=batch,
            tenant_id=tenant_id,
            public_id=public_id,
            apply_token=apply_token,
            now=now_utc(),
        )
        db.commit()
        db.refresh(batch)
        return CsvImportApplyResponse(
            batch=CsvImportBatchResponse.model_validate(batch),
            inserted_count=inserted,
            remaining_valid_rows=remaining_rows,
        )
    except AppError:
        db.rollback()
        if claimed_row_ids:
            _reset_claimed_csv_import_rows(
                db,
                tenant_id=tenant_id,
                row_ids=claimed_row_ids,
                apply_token=apply_token,
            )
            _mark_csv_import_apply_failed(
                db,
                tenant_id=tenant_id,
                public_id=public_id,
                apply_token=apply_token,
            )
        else:
            _release_csv_import_apply_lease(
                db,
                tenant_id=tenant_id,
                public_id=public_id,
                apply_token=apply_token,
            )
        raise
    except IntegrityError as exc:
        db.rollback()
        resolved = _resolve_csv_import_idempotency_conflict(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            row_ids=claimed_row_ids,
            apply_token=apply_token,
        )
        if resolved is not None:
            return resolved
        _reset_claimed_csv_import_rows(
            db,
            tenant_id=tenant_id,
            row_ids=claimed_row_ids,
            apply_token=apply_token,
        )
        _mark_csv_import_apply_failed(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            apply_token=apply_token,
        )
        raise AppError(
            "import_batch_conflict",
            "导入批次状态已变化，请刷新后重试。",
            status_code=409,
        ) from exc
    except Exception:  # noqa: BLE001 — final apply rollback must catch everything
        db.rollback()
        _reset_claimed_csv_import_rows(
            db,
            tenant_id=tenant_id,
            row_ids=claimed_row_ids,
            apply_token=apply_token,
        )
        _mark_csv_import_apply_failed(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            apply_token=apply_token,
        )
        raise
