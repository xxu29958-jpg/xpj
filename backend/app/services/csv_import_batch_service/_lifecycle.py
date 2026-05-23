"""Non-apply public API: create / get / list batches and rows.

The ``create`` path parses an uploaded CSV file into ``CsvImportRow``
records (status ``valid`` or ``error``); ``apply`` then promotes ``valid``
rows to ``Expense`` rows in :mod:`._apply`.
"""

from __future__ import annotations

import csv
from io import TextIOWrapper
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow
from app.schemas import (
    CsvImportBatchResponse,
    CsvImportRowsResponse,
)
from app.services.csv_import_batch_service._common import MAX_CSV_IMPORT_ROWS
from app.services.csv_import_batch_service._csv_io import _clean_file_name, _row_from_parsed
from app.services.csv_import_batch_service._queries import get_csv_import_batch  # re-exported
from app.services.import_service import parse_csv_row
from app.services.time_service import now_utc

_ = get_csv_import_batch  # quiet F401: re-exported through this module's surface


def create_csv_import_batch(
    db: Session,
    *,
    tenant_id: str,
    file_name: str | None,
    file_obj: BinaryIO,
) -> CsvImportBatch:
    try:
        text_stream = TextIOWrapper(file_obj, encoding="utf-8-sig", newline="")
        reader = csv.reader(text_stream)
        header_row = next(reader, None)
        if header_row is None:
            raise AppError("invalid_request", "CSV 缺少表头。", status_code=400)
        headers = [header.strip().lstrip("﻿").lower() for header in header_row]
        if not any(header in {"amount_yuan", "amount_cents"} for header in headers):
            raise AppError(
                "invalid_request",
                "CSV 必须包含 amount_yuan 或 amount_cents 列。",
                status_code=400,
            )

        now = now_utc()
        batch = CsvImportBatch(
            tenant_id=tenant_id,
            file_name=_clean_file_name(file_name),
            status="parsed",
            created_at=now,
            updated_at=now,
        )
        db.add(batch)
        db.flush()

        total_rows = 0
        valid_rows = 0
        error_rows = 0
        timezone_name = get_settings().ocr_default_timezone
        for line_number, row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in row):
                continue
            total_rows += 1
            if total_rows > MAX_CSV_IMPORT_ROWS:
                raise AppError(
                    "invalid_request",
                    f"CSV 一次最多导入 {MAX_CSV_IMPORT_ROWS} 行。",
                    status_code=400,
                )
            parsed = parse_csv_row(
                headers,
                row,
                line_number=line_number,
                timezone_name=timezone_name,
            )
            if parsed.is_valid:
                valid_rows += 1
            else:
                error_rows += 1
            db.add(_row_from_parsed(batch, parsed))

        batch.total_rows = total_rows
        batch.valid_rows = valid_rows
        batch.error_rows = error_rows
        batch.status = "parsed_with_errors" if error_rows else "parsed"
        batch.updated_at = now_utc()
        db.commit()
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
