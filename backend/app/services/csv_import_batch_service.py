from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO, TextIOWrapper
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportRow, Expense
from app.schemas import (
    CsvImportApplyResponse,
    CsvImportBatchResponse,
    CsvImportRowsResponse,
)
from app.services.csv_security import safe_csv_cell
from app.services.exchange_rate_service import apply_currency_payload, home_currency_code
from app.services.import_service import DEFAULT_SOURCE, parse_csv_row
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc


MAX_CSV_IMPORT_ROWS = 20_000
DEFAULT_BATCH_FILE_NAME = "import.csv"
APPLY_LEASE_MINUTES = 5
ROW_APPLY_LEASE_MINUTES = APPLY_LEASE_MINUTES


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
        headers = [header.strip().lstrip("\ufeff").lower() for header in header_row]
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


def get_csv_import_batch(db: Session, *, tenant_id: str, public_id: str) -> CsvImportBatch:
    batch = db.scalar(
        ledger_scoped_select(CsvImportBatch, tenant_id).where(
            CsvImportBatch.public_id == public_id
        )
    )
    if batch is None:
        raise AppError("import_batch_not_found", "导入批次不存在。", status_code=404)
    return batch


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
    except Exception:
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


def _claim_apply_lease(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> CsvImportBatch:
    now = now_utc()
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
            locked_until=now + timedelta(minutes=APPLY_LEASE_MINUTES),
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


def _mark_csv_import_apply_failed(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    apply_token: str,
) -> None:
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


def _resolve_csv_import_idempotency_conflict(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    row_ids: list[int],
    apply_token: str,
) -> CsvImportApplyResponse | None:
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


def build_csv_import_errors_csv(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> str:
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


def _row_from_parsed(batch: CsvImportBatch, parsed) -> CsvImportRow:
    return CsvImportRow(
        tenant_id=batch.tenant_id,
        batch_id=batch.id,
        line_number=parsed.line_number,
        status="valid" if parsed.is_valid else "error",
        error_code=None if parsed.is_valid else "invalid_row",
        error_message=parsed.error,
        amount_cents=parsed.amount_cents,
        original_currency_code=parsed.original_currency_code,
        original_amount_minor=parsed.original_amount_minor,
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


def _clean_file_name(value: str | None) -> str:
    cleaned = Path(value or DEFAULT_BATCH_FILE_NAME).name.strip()
    return cleaned[:255] if cleaned else DEFAULT_BATCH_FILE_NAME


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
