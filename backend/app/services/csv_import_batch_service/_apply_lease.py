"""Batch-level lease management for the CSV import apply phase.

Each ``CsvImportBatch`` transitions ``parsed → applying → applied`` (or
``applied_with_errors`` / ``parsed_with_errors`` for partial outcomes).
The ``applying`` state is gated by ``apply_token`` + ``locked_until`` so
two concurrent apply requests cannot overlap; expired leases free the
batch back to ``parsed``.

All five functions in this module assume the caller already holds (or
is about to claim) the apply_token returned by ``_claim_apply_lease``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import CsvImportBatch
from app.services.csv_import_batch_service._csv_io import _refresh_batch_counts
from app.services.csv_import_batch_service._row_claim import (
    _applying_row_count,
    _remaining_importable_rows,
)
from app.services.time_service import ensure_utc, now_utc


def _claim_apply_lease(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> CsvImportBatch:
    # Lazy import to avoid an apply_lease ↔ lifecycle cycle.
    from app.services.csv_import_batch_service._queries import get_csv_import_batch

    now = now_utc()
    lease_minutes = get_settings().csv_import_apply_lease_minutes
    result = db.execute(
        update(CsvImportBatch)
        .where(CsvImportBatch.tenant_id == tenant_id)
        .where(CsvImportBatch.public_id == public_id)
        .where(CsvImportBatch.status.in_(("parsed", "parsed_with_errors", "applying")))
        .where(
            or_(
                CsvImportBatch.locked_until.is_(None),
                CsvImportBatch.locked_until <= now,
            )
        )
        .values(
            locked_until=now + timedelta(minutes=lease_minutes),
            apply_token=apply_token,
            status="applying",
            last_error=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
        locked_until = ensure_utc(batch.locked_until)
        if locked_until is not None and locked_until > now:
            raise AppError("invalid_request", "导入批次正在应用中，请稍后重试。", status_code=409)
        raise AppError("invalid_request", "导入批次状态已变更，请重试。", status_code=409)

    db.commit()
    db.expire_all()
    return get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)


def _mark_csv_import_apply_failed(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> None:
    from app.services.csv_import_batch_service._queries import get_csv_import_batch

    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    if batch.apply_token != apply_token:
        return
    batch.locked_until = None
    batch.apply_token = None
    batch.status = "parsed_with_errors" if batch.error_rows else "parsed"
    batch.last_error = "导入应用失败。"
    batch.updated_at = now_utc()
    db.commit()


def _release_csv_import_apply_lease(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> None:
    from app.services.csv_import_batch_service._queries import get_csv_import_batch

    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    if batch.apply_token != apply_token:
        return
    batch.locked_until = None
    batch.apply_token = None
    batch.status = "applying" if _applying_row_count(db, batch, tenant_id) else (
        "parsed_with_errors" if batch.error_rows else "parsed"
    )
    batch.updated_at = now_utc()
    db.commit()


def _batch_apply_token_matches(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> bool:
    return bool(
        db.scalar(
            select(CsvImportBatch.id)
            .where(CsvImportBatch.tenant_id == tenant_id)
            .where(CsvImportBatch.public_id == public_id)
            .where(CsvImportBatch.apply_token == apply_token)
        )
    )


def _finalize_csv_import_apply_success(
    db: Session,
    *,
    batch: CsvImportBatch,
    tenant_id: str,
    public_id: str,
    apply_token: str,
    now: datetime,
) -> int:
    _refresh_batch_counts(db, batch)
    batch.updated_at = now
    remaining_rows = _remaining_importable_rows(db, batch, tenant_id)
    if _batch_apply_token_matches(db, tenant_id=tenant_id, public_id=public_id, apply_token=apply_token):
        batch.locked_until = None
        batch.apply_token = None
        batch.last_error = None
        if remaining_rows == 0:
            batch.applied_at = now
            batch.status = "applied_with_errors" if batch.error_rows else "applied"
        else:
            batch.status = "parsed_with_errors" if batch.error_rows else "parsed"
    return remaining_rows
