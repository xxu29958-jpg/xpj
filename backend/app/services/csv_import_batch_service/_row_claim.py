"""Row-level lease management for the CSV import apply phase.

Each row in a batch transitions ``valid → applying → applied`` (or
``insert_failed``) during apply. The ``applying`` state is gated by a
per-row ``apply_token`` so concurrent applies cannot double-process a
row. Stale ``applying`` rows are reclaimed after the lease window so a
crashed worker doesn't permanently lock the batch.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow
from app.services.time_service import now_utc


def _claim_csv_import_rows(
    db: Session,
    *,
    tenant_id: str,
    batch_id: int,
    batch_size: int,
    apply_token: str,
) -> list[int]:
    capped = max(1, min(int(batch_size or 1), 1000))
    row_ids = list(
        db.scalars(
            ledger_scoped_select(CsvImportRow, tenant_id)
            .where(CsvImportRow.batch_id == batch_id)
            .where(CsvImportRow.status == "valid")
            .order_by(CsvImportRow.line_number.asc())
            .limit(capped)
            .with_only_columns(CsvImportRow.id)
        )
    )
    if not row_ids:
        return []
    now = now_utc()
    result = db.execute(
        update(CsvImportRow)
        .where(CsvImportRow.tenant_id == tenant_id)
        .where(CsvImportRow.batch_id == batch_id)
        .where(CsvImportRow.id.in_(row_ids))
        .where(CsvImportRow.status == "valid")
        .values(status="applying", apply_token=apply_token, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.expire_all()
    if result.rowcount != len(row_ids):
        return list(
            db.scalars(
                ledger_scoped_select(CsvImportRow, tenant_id)
                .where(CsvImportRow.batch_id == batch_id)
                .where(CsvImportRow.id.in_(row_ids))
                .where(CsvImportRow.status == "applying")
                .where(CsvImportRow.apply_token == apply_token)
                .with_only_columns(CsvImportRow.id)
            )
        )
    return [int(row_id) for row_id in row_ids]


def _reset_claimed_csv_import_rows(
    db: Session,
    *,
    tenant_id: str,
    row_ids: list[int],
    apply_token: str,
) -> None:
    if not row_ids:
        return
    db.execute(
        update(CsvImportRow)
        .where(CsvImportRow.tenant_id == tenant_id)
        .where(CsvImportRow.id.in_(row_ids))
        .where(CsvImportRow.status == "applying")
        .where(CsvImportRow.apply_token == apply_token)
        .where(CsvImportRow.expense_id.is_(None))
        .values(status="valid", apply_token=None, updated_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    db.commit()


def _refresh_claimed_csv_import_row(
    db: Session,
    *,
    tenant_id: str,
    row_id: int,
    apply_token: str,
    now: datetime,
) -> bool:
    result = db.execute(
        update(CsvImportRow)
        .where(CsvImportRow.tenant_id == tenant_id)
        .where(CsvImportRow.id == row_id)
        .where(CsvImportRow.status == "applying")
        .where(CsvImportRow.apply_token == apply_token)
        .where(CsvImportRow.expense_id.is_(None))
        .values(updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _recover_stale_csv_import_rows(
    db: Session,
    *,
    tenant_id: str,
    batch_id: int,
    stale_before: datetime,
) -> int:
    result = db.execute(
        update(CsvImportRow)
        .where(CsvImportRow.tenant_id == tenant_id)
        .where(CsvImportRow.batch_id == batch_id)
        .where(CsvImportRow.status == "applying")
        .where(CsvImportRow.expense_id.is_(None))
        .where(CsvImportRow.updated_at <= stale_before)
        .values(status="valid", apply_token=None, updated_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    recovered = int(result.rowcount or 0)
    if recovered:
        db.commit()
        db.expire_all()
    return recovered


def _applying_row_count(db: Session, batch: CsvImportBatch, tenant_id: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(
                ledger_scoped_select(CsvImportRow, tenant_id)
                .where(CsvImportRow.batch_id == batch.id)
                .where(CsvImportRow.status == "applying")
                .subquery()
            )
        )
        or 0
    )


def _remaining_importable_rows(db: Session, batch: CsvImportBatch, tenant_id: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(
                ledger_scoped_select(CsvImportRow, tenant_id)
                .where(CsvImportRow.batch_id == batch.id)
                .where(CsvImportRow.status.in_(("valid", "applying")))
                .subquery()
            )
        )
        or 0
    )
