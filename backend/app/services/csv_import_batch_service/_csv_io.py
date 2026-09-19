"""CSV input/output helpers for the import batch lifecycle.

Pure-ish I/O — row materialisation, file-name cleanup, error-CSV
formatting, count refresh queries. Knows nothing about leases /
idempotency / applying state.
"""

from __future__ import annotations

import csv
import re
from io import StringIO
from pathlib import Path

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow
from app.money_contract import MoneySign, ensure_optional_money_minor
from app.services.csv_import_batch_service._common import DEFAULT_BATCH_FILE_NAME
from app.services.csv_import_batch_service._queries import _csv_import_batch_counts
from app.services.csv_security import safe_csv_cell
from app.services.import_financial_events import NATIVE_CSV_INPUT_COLUMNS
from app.services.import_service import DEFAULT_SOURCE
from app.services.time_service import now_utc

_NUMERIC_CSV_COLUMNS = {
    "amount_cents", "amount_yuan", "amount_home_major", "original_amount_minor",
    "exchange_rate_to_cny", "stream_amount_cents", "lineage_home_net_cents",
}


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
        entry_kind=parsed.entry_kind,
        offset_kind=parsed.offset_kind,
        source_event_public_id=parsed.source_event_public_id,
        source_root_public_id=parsed.source_root_public_id,
        accounting_date=parsed.accounting_date,
        stream_amount_cents=parsed.stream_amount_cents,
        lineage_status=parsed.lineage_status,
        lineage_home_net_cents=parsed.lineage_home_net_cents,
        event_input=parsed.event_input,
        amount_cents=amount_cents,
        home_currency_code=parsed.home_currency_code,
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
    counts = _csv_import_batch_counts(db, tenant_id=batch.tenant_id, batch_id=batch.id)
    batch.applied_rows = counts.applied_rows
    batch.inserted_count = counts.inserted_count
    batch.error_rows = counts.error_rows


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
            .where(CsvImportRow.status.in_(("error", "insert_failed", "conflict")))
            .order_by(CsvImportRow.line_number.asc())
        )
    )
    output = StringIO()
    writer = csv.writer(output)
    headers = [
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
    headers.extend(name for name in NATIVE_CSV_INPUT_COLUMNS if name not in headers)
    writer.writerow(headers)
    for row in rows:
        values = _error_csv_values(row)
        writer.writerow([_error_csv_cell(name, values.get(name)) for name in headers])
    return output.getvalue()


def _error_csv_values(row: CsvImportRow) -> dict[str, object]:
    values = {
        "line_number": row.line_number, "status": row.status, "error_code": row.error_code,
        "error_message": row.error_message, "amount_cents": row.amount_cents,
        "home_currency_code": row.home_currency_code, "original_currency_code": row.original_currency_code,
        "original_amount_minor": row.original_amount_minor, "exchange_rate_to_cny": row.exchange_rate_to_cny,
        "exchange_rate_date": row.exchange_rate_date, "exchange_rate_source": row.exchange_rate_source,
        "merchant": row.merchant, "category": row.category, "note": row.note,
        "expense_time": row.expense_time.isoformat() if row.expense_time else "", "tags": row.tags, "source": row.source,
        "entry_kind": row.entry_kind if row.event_input is not None or row.source_event_public_id is not None else "",
        "offset_kind": row.offset_kind, "public_id": row.source_event_public_id,
        "root_expense_public_id": row.source_root_public_id, "stream_date": row.accounting_date,
        "stream_amount_cents": row.stream_amount_cents, "lineage_status": row.lineage_status,
        "lineage_home_net_cents": row.lineage_home_net_cents,
    }
    # Invalid typed values are NULL; the original cells remain repairable.
    values.update(row.event_input or {})
    return values


def _error_csv_cell(name: str, value: object) -> object:
    if name in _NUMERIC_CSV_COLUMNS and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", str(value)):
        return value
    return safe_csv_cell(value)
