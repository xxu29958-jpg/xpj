"""CSV input/output helpers for the import batch lifecycle.

Pure-ish I/O — row materialisation, file-name cleanup, error-CSV
formatting, count refresh queries. Knows nothing about leases /
idempotency / applying state.
"""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow
from app.money_contract import MoneySign, ensure_optional_money_minor
from app.services.csv_import_batch_service._common import DEFAULT_BATCH_FILE_NAME
from app.services.csv_security import safe_csv_cell
from app.services.import_service import DEFAULT_SOURCE
from app.services.time_service import now_utc


def _clean_file_name(value: str | None) -> str:
    cleaned = Path(value or DEFAULT_BATCH_FILE_NAME).name.strip()
    return cleaned[:255] if cleaned else DEFAULT_BATCH_FILE_NAME


def _row_from_parsed(batch: CsvImportBatch, parsed) -> CsvImportRow:
    try:
        amount_cents = ensure_optional_money_minor(
            parsed.amount_cents,
            sign=MoneySign.NONNEGATIVE,
            label="csv_import_row.amount_cents",
        )
        original_amount_minor = ensure_optional_money_minor(
            parsed.original_amount_minor,
            sign=MoneySign.NONNEGATIVE,
            label="csv_import_row.original_amount_minor",
        )
    except AppError:
        amount_cents = None
        original_amount_minor = None
        valid = False
        error_code = parsed.error_code or "amount_out_of_range"
        error_message = parsed.error or "金额超出当前版本可支持范围"
    else:
        valid = parsed.is_valid
        error_code = None if valid else (parsed.error_code or "invalid_row")
        error_message = parsed.error
    return CsvImportRow(
        tenant_id=batch.tenant_id,
        batch_id=batch.id,
        line_number=parsed.line_number,
        status="valid" if valid else "error",
        error_code=error_code,
        error_message=error_message,
        amount_cents=amount_cents,
        original_currency_code=parsed.original_currency_code,
        original_amount_minor=original_amount_minor,
        exchange_rate_to_cny=parsed.exchange_rate_to_cny,
        exchange_rate_date=parsed.exchange_rate_date,
        exchange_rate_source=parsed.exchange_rate_source,
        merchant=parsed.merchant or None,
        category=parsed.category or "其他",
        note=parsed.note or None,
        expense_time=parsed.expense_time,
        tags=parsed.tags or None,
        source=parsed.source or DEFAULT_SOURCE,
        created_at=now_utc(),
        updated_at=now_utc(),
    )


def _refresh_batch_counts(db: Session, batch: CsvImportBatch) -> None:
    counts = dict(
        db.execute(
            select(CsvImportRow.status, func.count())
            .where(CsvImportRow.tenant_id == batch.tenant_id)
            .where(CsvImportRow.batch_id == batch.id)
            .group_by(CsvImportRow.status)
        ).all()
    )
    batch.applied_rows = int(counts.get("applied", 0))
    batch.inserted_count = batch.applied_rows
    batch.error_rows = int(counts.get("error", 0)) + int(counts.get("insert_failed", 0))


def build_csv_import_errors_csv(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> str:
    # Lazy import to avoid pulling lifecycle into csv_io.
    from app.services.csv_import_batch_service._queries import get_csv_import_batch

    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    rows = list(
        db.scalars(
            ledger_scoped_select(CsvImportRow, tenant_id)
            .where(CsvImportRow.batch_id == batch.id)
            .where(CsvImportRow.status.in_(("error", "insert_failed")))
            .order_by(CsvImportRow.line_number.asc())
        )
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "line_number",
            "status",
            "error_code",
            "error_message",
            "amount_cents",
            "amount_yuan",
            "original_currency_code",
            "original_amount_minor",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "merchant",
            "category",
            "note",
            "expense_time",
            "tags",
            "source",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.line_number,
                row.status,
                safe_csv_cell(row.error_code or ""),
                safe_csv_cell(row.error_message or ""),
                row.amount_cents if row.amount_cents is not None else "",
                "",
                row.original_currency_code,
                row.original_amount_minor if row.original_amount_minor is not None else "",
                row.exchange_rate_to_cny if row.exchange_rate_to_cny is not None else "",
                row.exchange_rate_date.isoformat() if row.exchange_rate_date else "",
                safe_csv_cell(row.merchant or ""),
                safe_csv_cell(row.category),
                safe_csv_cell(row.note or ""),
                row.expense_time.isoformat() if row.expense_time else "",
                safe_csv_cell(row.tags or ""),
                safe_csv_cell(row.source),
            ]
        )
    return output.getvalue()
