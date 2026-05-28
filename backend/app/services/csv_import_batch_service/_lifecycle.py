"""Non-apply public API: create / get / list batches and rows."""

from __future__ import annotations

import csv
from io import BytesIO, TextIOWrapper
from typing import BinaryIO

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow
from app.schemas import CsvImportBatchResponse, CsvImportRowsResponse
from app.services.csv_import_batch_service._common import (
    CREATE_BATCH_INSERT_CHUNK_SIZE,
    MAX_CSV_IMPORT_ROWS,
)
from app.services.csv_import_batch_service._csv_io import (
    _clean_file_name,
    _row_from_parsed,
)
from app.services.csv_import_batch_service._queries import get_csv_import_batch
from app.services.import_service import ParsedRow, parse_csv_row
from app.services.time_service import now_utc

_ = get_csv_import_batch  # quiet F401: re-exported through this module's surface


def _read_csv_bounded(file_obj: BinaryIO, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes
    while True:
        chunk = file_obj.read(min(remaining + 1, 64 * 1024))
        if not chunk:
            break
        remaining -= len(chunk)
        if remaining < 0:
            raise AppError(
                "invalid_request",
                f"CSV 文件超过 {max_bytes} 字节上限。",
                status_code=413,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _assert_cells_bounded(row: list[str], *, max_cell_bytes: int) -> None:
    for cell in row:
        if len(cell.encode("utf-8")) > max_cell_bytes:
            raise AppError(
                "invalid_request",
                f"CSV 单元格超过 {max_cell_bytes} 字节上限。",
                status_code=400,
            )


def _delete_partial_csv_import_batch(
    db: Session, *, batch_id: int, tenant_id: str
) -> None:
    db.execute(
        delete(CsvImportRow)
        .where(CsvImportRow.tenant_id == tenant_id)
        .where(CsvImportRow.batch_id == batch_id)
    )
    db.execute(
        delete(CsvImportBatch)
        .where(CsvImportBatch.tenant_id == tenant_id)
        .where(CsvImportBatch.id == batch_id)
    )
    db.commit()


def _csv_import_limits() -> tuple[int, int, int, int, str]:
    cfg = get_settings()
    max_bytes = max(cfg.csv_import_max_bytes, 1)
    max_lines = max(cfg.csv_import_max_lines, 1)
    max_cell_bytes = max(cfg.csv_import_max_cell_bytes, 1)
    return (
        max_bytes,
        max_cell_bytes,
        min(MAX_CSV_IMPORT_ROWS, max_lines),
        CREATE_BATCH_INSERT_CHUNK_SIZE,
        cfg.ocr_default_timezone,
    )


def _read_csv_import_header(reader, *, max_cell_bytes: int) -> list[str]:
    header_row = next(reader, None)
    if header_row is None:
        raise AppError("invalid_request", "CSV 缺少表头。", status_code=400)
    _assert_cells_bounded(header_row, max_cell_bytes=max_cell_bytes)
    headers = [header.strip().lstrip("\ufeff").lower() for header in header_row]
    if not any(header in {"amount_yuan", "amount_cents"} for header in headers):
        raise AppError(
            "invalid_request",
            "CSV 必须包含 amount_yuan 或 amount_cents 列。",
            status_code=400,
        )
    return headers


def _parse_csv_import_rows(
    file_obj: BinaryIO,
    *,
    max_bytes: int,
    max_cell_bytes: int,
    max_data_rows: int,
    timezone_name: str,
) -> tuple[list[ParsedRow], int, int, int]:
    raw_bytes = _read_csv_bounded(file_obj, max_bytes=max_bytes)
    text_stream = TextIOWrapper(BytesIO(raw_bytes), encoding="utf-8-sig", newline="")
    reader = csv.reader(text_stream)
    headers = _read_csv_import_header(reader, max_cell_bytes=max_cell_bytes)

    parsed_rows: list[ParsedRow] = []
    valid_rows = 0
    error_rows = 0
    for line_number, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(parsed_rows) >= max_data_rows:
            raise AppError(
                "invalid_request",
                f"CSV 一次最多导入 {max_data_rows} 行。",
                status_code=400,
            )
        _assert_cells_bounded(row, max_cell_bytes=max_cell_bytes)
        parsed = parse_csv_row(
            headers,
            row,
            line_number=line_number,
            timezone_name=timezone_name,
        )
        valid_rows += 1 if parsed.is_valid else 0
        error_rows += 0 if parsed.is_valid else 1
        parsed_rows.append(parsed)
    return parsed_rows, len(parsed_rows), valid_rows, error_rows


def _create_csv_import_batch_record(
    db: Session,
    *,
    tenant_id: str,
    file_name: str | None,
    total_rows: int,
    valid_rows: int,
    error_rows: int,
) -> CsvImportBatch:
    now = now_utc()
    batch = CsvImportBatch(
        tenant_id=tenant_id,
        file_name=_clean_file_name(file_name),
        status="parsed_with_errors" if error_rows else "parsed",
        total_rows=total_rows,
        valid_rows=valid_rows,
        error_rows=error_rows,
        created_at=now,
        updated_at=now,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def _insert_csv_import_rows_in_chunks(
    db: Session,
    *,
    batch: CsvImportBatch,
    parsed_rows: list[ParsedRow],
    chunk_size: int,
) -> None:
    for start in range(0, len(parsed_rows), chunk_size):
        chunk = parsed_rows[start : start + chunk_size]
        for parsed in chunk:
            db.add(_row_from_parsed(batch, parsed))
        db.commit()


def create_csv_import_batch(
    db: Session,
    *,
    tenant_id: str,
    file_name: str | None,
    file_obj: BinaryIO,
) -> CsvImportBatch:
    max_bytes, max_cell_bytes, max_data_rows, chunk_size, timezone_name = (
        _csv_import_limits()
    )
    try:
        parsed_rows, total_rows, valid_rows, error_rows = _parse_csv_import_rows(
            file_obj,
            max_bytes=max_bytes,
            max_cell_bytes=max_cell_bytes,
            max_data_rows=max_data_rows,
            timezone_name=timezone_name,
        )
        batch = _create_csv_import_batch_record(
            db,
            tenant_id=tenant_id,
            file_name=file_name,
            total_rows=total_rows,
            valid_rows=valid_rows,
            error_rows=error_rows,
        )
        try:
            _insert_csv_import_rows_in_chunks(
                db, batch=batch, parsed_rows=parsed_rows, chunk_size=chunk_size
            )
        except SQLAlchemyError:
            db.rollback()
            _delete_partial_csv_import_batch(
                db,
                batch_id=batch.id,
                tenant_id=tenant_id,
            )
            raise

        db.refresh(batch)
        return batch
    except UnicodeDecodeError as exc:
        db.rollback()
        raise AppError("invalid_request", "CSV 必须使用 UTF-8 编码。", status_code=400) from exc
    except csv.Error as exc:
        db.rollback()
        raise AppError("invalid_request", f"CSV 格式无效：{exc}", status_code=400) from exc
    except AppError:
        db.rollback()
        raise


def list_csv_import_rows(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
) -> CsvImportRowsResponse:
    batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 500)
    query = ledger_scoped_select(CsvImportRow, tenant_id).where(
        CsvImportRow.batch_id == batch.id
    )
    if status:
        query = query.where(CsvImportRow.status == status)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list(
        db.scalars(
            query.order_by(CsvImportRow.line_number.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return CsvImportRowsResponse(
        batch=CsvImportBatchResponse.model_validate(batch),
        items=rows,
        page=page,
        page_size=page_size,
        total=total,
    )
