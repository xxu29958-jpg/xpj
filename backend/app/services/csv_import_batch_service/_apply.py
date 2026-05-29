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

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow, Expense
from app.schemas import CsvImportApplyResponse, CsvImportBatchResponse
from app.services.csv_import_batch_service._apply_lease import (
    _claim_apply_lease,
    _finalize_csv_import_apply_success,
    _mark_csv_import_apply_failed,
    _release_csv_import_apply_lease,
)
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


def _process_csv_import_apply_row(
    db: Session,
    *,
    row: CsvImportRow,
    batch: CsvImportBatch,
    tenant_id: str,
    apply_token: str,
    now: datetime,
) -> Expense | None:
    """Run one CSV row through the apply pipeline.

    Returns the new ``Expense`` for the caller to ``db.add`` and pair
    with ``row`` after flush, or ``None`` when the row was skipped or
    handled in place (insert_failed / already-applied idempotency hit /
    stale claim).
    """
    if not _refresh_claimed_csv_import_row(
        db, tenant_id=tenant_id, row_id=row.id, apply_token=apply_token, now=now
    ):
        return None
    if row.amount_cents is None and row.original_amount_minor is None:
        row.status = "insert_failed"
        row.apply_token = None
        row.error_code = "amount_required"
        row.error_message = "缺少有效金额。"
        row.updated_at = now
        return None
    idempotency_key = _csv_import_row_idempotency_key(batch, row)
    existing_expense_id = _existing_csv_import_expense_id(
        db, tenant_id=tenant_id, idempotency_key=idempotency_key
    )
    if existing_expense_id is not None:
        row.status = "applied"
        row.apply_token = None
        row.expense_id = existing_expense_id
        row.updated_at = now
        return None
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
    return expense


def _cleanup_csv_import_apply_app_error(
    db: Session,
    *,
    claimed_row_ids: list[int],
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> None:
    """Cleanup path for AppError: caller-level validation rejected the
    batch before any rows mutated, so an empty claim set means we
    only need to release the apply lease (no row reset needed)."""
    if claimed_row_ids:
        _reset_claimed_csv_import_rows(
            db, tenant_id=tenant_id, row_ids=claimed_row_ids, apply_token=apply_token
        )
        _mark_csv_import_apply_failed(
            db, tenant_id=tenant_id, public_id=public_id, apply_token=apply_token
        )
    else:
        _release_csv_import_apply_lease(
            db, tenant_id=tenant_id, public_id=public_id, apply_token=apply_token
        )


def _cleanup_csv_import_apply_failure(
    db: Session,
    *,
    claimed_row_ids: list[int],
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> None:
    """Cleanup path for IntegrityError / unexpected Exception:
    rows were already claimed and partially mutated, so always reset
    + mark failed."""
    _reset_claimed_csv_import_rows(
        db, tenant_id=tenant_id, row_ids=claimed_row_ids, apply_token=apply_token
    )
    _mark_csv_import_apply_failed(
        db, tenant_id=tenant_id, public_id=public_id, apply_token=apply_token
    )


def _mark_csv_import_row_insert_failed(
    db: Session,
    *,
    tenant_id: str,
    row_id: int,
    apply_token: str,
    error_code: str,
    error_message: str,
    now: datetime,
) -> None:
    row = db.scalar(
        select(CsvImportRow)
        .where(CsvImportRow.tenant_id == tenant_id)
        .where(CsvImportRow.id == row_id)
        .where(CsvImportRow.status == "applying")
        .where(CsvImportRow.apply_token == apply_token)
        .limit(1)
    )
    if row is None:
        return
    row.status = "insert_failed"
    row.apply_token = None
    row.error_code = error_code
    row.error_message = error_message[:255]
    row.updated_at = now
    db.commit()


def _mark_csv_import_row_applied_if_existing(
    db: Session,
    *,
    batch: CsvImportBatch,
    tenant_id: str,
    row_id: int,
    apply_token: str,
    now: datetime,
) -> bool:
    row = db.scalar(
        select(CsvImportRow)
        .where(CsvImportRow.tenant_id == tenant_id)
        .where(CsvImportRow.batch_id == batch.id)
        .where(CsvImportRow.id == row_id)
        .where(CsvImportRow.status == "applying")
        .where(CsvImportRow.apply_token == apply_token)
        .limit(1)
    )
    if row is None:
        return False
    existing_expense_id = _existing_csv_import_expense_id(
        db,
        tenant_id=tenant_id,
        idempotency_key=_csv_import_row_idempotency_key(batch, row),
    )
    if existing_expense_id is None:
        return False
    row.status = "applied"
    row.apply_token = None
    row.expense_id = existing_expense_id
    row.updated_at = now
    db.commit()
    return True


def _apply_one_claimed_csv_import_row(
    db: Session,
    *,
    row_id: int,
    batch: CsvImportBatch,
    tenant_id: str,
    apply_token: str,
    now: datetime,
) -> int:
    row = db.scalar(
        ledger_scoped_select(CsvImportRow, tenant_id)
        .where(CsvImportRow.batch_id == batch.id)
        .where(CsvImportRow.id == row_id)
        .where(CsvImportRow.status == "applying")
        .where(CsvImportRow.apply_token == apply_token)
        .limit(1)
    )
    if row is None:
        return 0
    try:
        expense = _process_csv_import_apply_row(
            db,
            row=row,
            batch=batch,
            tenant_id=tenant_id,
            apply_token=apply_token,
            now=now,
        )
        if expense is None:
            db.commit()
            return 0

        db.add(expense)
        db.flush()
        sync_expense_tags(db, expense)
        row.status = "applied"
        row.apply_token = None
        row.expense_id = expense.id
        row.updated_at = now
        db.flush()
        db.commit()
        return 1
    except IntegrityError:
        db.rollback()
        if _mark_csv_import_row_applied_if_existing(
            db,
            batch=batch,
            tenant_id=tenant_id,
            row_id=row_id,
            apply_token=apply_token,
            now=now,
        ):
            return 0
        _mark_csv_import_row_insert_failed(
            db,
            tenant_id=tenant_id,
            row_id=row_id,
            apply_token=apply_token,
            error_code="insert_failed",
            error_message="CSV row insert failed; row was not imported.",
            now=now,
        )
        return 0
    except AppError as exc:
        db.rollback()
        _mark_csv_import_row_insert_failed(
            db,
            tenant_id=tenant_id,
            row_id=row_id,
            apply_token=apply_token,
            error_code=exc.error,
            error_message=exc.message,
            now=now,
        )
        return 0


def _attempt_csv_import_apply(
    db: Session,
    *,
    batch: CsvImportBatch,
    tenant_id: str,
    public_id: str,
    apply_token: str,
    batch_size: int,
    claimed_row_ids: list[int],
) -> CsvImportApplyResponse:
    """Happy-path body of :func:`apply_csv_import_batch`.

    ``claimed_row_ids`` is the caller's mutable list — we ``extend`` it
    in-place so the outer ``except`` handlers can see which rows had
    already been claimed when a partial failure rolls back.
    """
    _recover_stale_csv_import_rows(
        db,
        tenant_id=tenant_id,
        batch_id=batch.id,
        stale_before=now_utc()
        - timedelta(minutes=get_settings().csv_import_row_apply_lease_minutes),
    )
    claimed_row_ids.extend(
        _claim_csv_import_rows(
            db,
            tenant_id=tenant_id,
            batch_id=batch.id,
            batch_size=batch_size,
            apply_token=apply_token,
        )
    )
    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    if not claimed_row_ids and _applying_row_count(db, batch, tenant_id) > 0:
        raise AppError("invalid_request", "导入批次正在应用中，请稍后重试。", status_code=409)
    now = now_utc()
    inserted = 0
    for row_id in claimed_row_ids:
        inserted += _apply_one_claimed_csv_import_row(
            db,
            row_id=row_id,
            batch=batch,
            tenant_id=tenant_id,
            apply_token=apply_token,
            now=now,
        )
    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
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


def apply_csv_import_batch(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    batch_size: int,
) -> CsvImportApplyResponse:
    apply_token = str(uuid4())
    batch = _claim_apply_lease(
        db, tenant_id=tenant_id, public_id=public_id, apply_token=apply_token
    )
    claimed_row_ids: list[int] = []
    try:
        return _attempt_csv_import_apply(
            db,
            batch=batch,
            tenant_id=tenant_id,
            public_id=public_id,
            apply_token=apply_token,
            batch_size=batch_size,
            claimed_row_ids=claimed_row_ids,
        )
    except AppError:
        db.rollback()
        _cleanup_csv_import_apply_app_error(
            db,
            claimed_row_ids=claimed_row_ids,
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
        _cleanup_csv_import_apply_failure(
            db,
            claimed_row_ids=claimed_row_ids,
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
        _cleanup_csv_import_apply_failure(
            db,
            claimed_row_ids=claimed_row_ids,
            tenant_id=tenant_id,
            public_id=public_id,
            apply_token=apply_token,
        )
        raise
