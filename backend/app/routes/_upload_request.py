from __future__ import annotations

import json
import logging
from collections.abc import Callable
from time import perf_counter
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.errors import AppError
from app.schemas import UploadResponse
from app.services.expense_service import create_pending_expense, enrich_pending_expense
from app.services.file_service import (
    SavedUpload,
    delete_relative_upload,
    save_upload,
    save_upload_bytes,
)

if TYPE_CHECKING:
    from app.models import Expense

IOS_SHORTCUT_FILE_FIELDS = ("file", "image", "photo", "screenshot")
logger = logging.getLogger("ticketbox.upload")


async def read_raw_body_limited(
    request: Request,
    *,
    max_size_bytes: int | None = None,
) -> bytes:
    limit = get_settings().max_upload_size_bytes
    if max_size_bytes is not None:
        limit = max(0, min(limit, int(max_size_bytes)))
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise AppError("file_too_large", status_code=413)
        chunks.append(chunk)
    return b"".join(chunks)


def elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def pick_first_upload_file(form) -> UploadFile | None:
    """Return the first upload file using the supported capture field order."""
    for field_name in IOS_SHORTCUT_FILE_FIELDS:
        value = form.get(field_name)
        if isinstance(value, UploadFile):
            return value
    for value in form.values():
        if isinstance(value, UploadFile):
            return value
    return None


async def save_request_upload(
    request: Request,
    tenant_id: str,
    *,
    max_size_bytes: int | None = None,
) -> tuple[SavedUpload, dict[str, int]]:
    timing_ms: dict[str, int] = {}
    limit = get_settings().max_upload_size_bytes
    if max_size_bytes is not None:
        limit = max(0, min(limit, int(max_size_bytes)))
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        try:
            form_context = request.form(
                max_files=4,
                max_fields=12,
                max_part_size=limit,
            )
            form_started_at = perf_counter()
            async with form_context as form:
                timing_ms["form_parse_ms"] = elapsed_ms(form_started_at)
                upload_file = pick_first_upload_file(form)
                if upload_file is not None:
                    save_started_at = perf_counter()
                    saved_file = await save_upload(
                        upload_file,
                        tenant_id,
                        max_size_bytes=limit,
                    )
                    timing_ms["file_save_ms"] = elapsed_ms(save_started_at)
                    return saved_file, timing_ms
        except StarletteHTTPException as exc:
            detail = str(exc.detail).lower()
            if "maximum size" in detail or "too large" in detail:
                raise AppError("file_too_large", status_code=413) from exc
            raise AppError("invalid_request", status_code=422) from exc

        raise AppError("invalid_request", "表单里没有找到图片文件。", status_code=422)

    read_started_at = perf_counter()
    body = await read_raw_body_limited(request, max_size_bytes=limit)
    timing_ms["body_read_ms"] = elapsed_ms(read_started_at)
    if not body:
        raise AppError("invalid_request", status_code=422)

    save_started_at = perf_counter()
    saved_file = save_upload_bytes(
        body,
        tenant_id=tenant_id,
        filename=request.headers.get("X-Upload-Filename"),
        content_type=content_type,
        max_size_bytes=limit,
    )
    timing_ms["file_save_ms"] = elapsed_ms(save_started_at)
    return saved_file, timing_ms


def upload_response(
    expense: Expense,
    saved_file: SavedUpload,
    duration_ms: int,
    timing_ms: dict[str, int],
) -> UploadResponse:
    return UploadResponse(
        id=expense.id,
        public_id=expense.public_id,
        status=expense.status,
        message="uploaded",
        image_hash=expense.image_hash or "",
        thumbnail_path=expense.thumbnail_path,
        duplicate_status=expense.duplicate_status,
        duplicate_of_id=expense.duplicate_of_id,
        upload_size_bytes=saved_file.size_bytes,
        duration_ms=duration_ms,
        timing_ms=timing_ms,
    )


async def handle_upload(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str,
    db: Session,
    source: str,
    endpoint: str,
    timezone_name: str | None = None,
    max_size_bytes: int | None = None,
    commit_guard: Callable[[], None] | None = None,
) -> UploadResponse:
    started_at = perf_counter()
    saved_file, timing_ms = await save_request_upload(
        request,
        tenant_id,
        max_size_bytes=max_size_bytes,
    )
    guard_passed = commit_guard is None
    try:
        if commit_guard is not None:
            commit_guard()
        guard_passed = True
    finally:
        if not guard_passed:
            db.rollback()
            delete_relative_upload(saved_file.relative_path)
    db_started_at = perf_counter()
    expense = create_pending_expense(
        db,
        saved_file,
        tenant_id,
        source=source,
        run_enrichment=False,
    )
    timing_ms["db_create_ms"] = elapsed_ms(db_started_at)
    duration_ms = elapsed_ms(started_at)
    timing_ms["total_ms"] = duration_ms
    logger.info(
        "upload accepted endpoint=%s ledger=%s expense_id=%s bytes=%s media_type=%s duration_ms=%s timing_ms=%s duplicate=%s",
        endpoint,
        tenant_id,
        expense.id,
        saved_file.size_bytes,
        saved_file.media_type,
        duration_ms,
        json.dumps(timing_ms, ensure_ascii=False, sort_keys=True),
        expense.duplicate_status,
    )
    background_tasks.add_task(
        enrich_pending_expense,
        expense.id,
        tenant_id,
        timezone_name,
    )
    return upload_response(expense, saved_file, duration_ms, timing_ms)
