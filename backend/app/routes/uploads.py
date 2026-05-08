from __future__ import annotations

import json
import logging
from time import perf_counter

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_current_app_tenant, get_current_upload_tenant
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.models import Expense
from app.schemas import UploadCheckResponse, UploadResponse
from app.services.expense_service import create_pending_expense, enrich_pending_expense
from app.services.file_service import ALLOWED_EXTENSIONS, SavedUpload, delete_saved_upload, save_upload, save_upload_bytes
from app.tenants import Tenant


router = APIRouter(prefix="/api", tags=["uploads"])
logger = logging.getLogger("ticketbox.upload")

IOS_SHORTCUT_FILE_FIELDS = ("file", "image", "photo", "screenshot")


async def _read_raw_body_limited(request: Request) -> bytes:
    limit = get_settings().max_upload_size_bytes
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise AppError("file_too_large", status_code=413)
        chunks.append(chunk)
    return b"".join(chunks)


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


async def _save_request_upload(request: Request) -> tuple[SavedUpload, dict[str, int]]:
    timing_ms: dict[str, int] = {}
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        try:
            form_context = request.form(
                max_files=4,
                max_fields=12,
                max_part_size=get_settings().max_upload_size_bytes,
            )
            form_started_at = perf_counter()
            async with form_context as form:
                timing_ms["form_parse_ms"] = _elapsed_ms(form_started_at)
                for field_name in IOS_SHORTCUT_FILE_FIELDS:
                    value = form.get(field_name)
                    if isinstance(value, UploadFile):
                        save_started_at = perf_counter()
                        saved_file = await save_upload(value)
                        timing_ms["file_save_ms"] = _elapsed_ms(save_started_at)
                        return saved_file, timing_ms

                for value in form.values():
                    if isinstance(value, UploadFile):
                        save_started_at = perf_counter()
                        saved_file = await save_upload(value)
                        timing_ms["file_save_ms"] = _elapsed_ms(save_started_at)
                        return saved_file, timing_ms
        except StarletteHTTPException as exc:
            detail = str(exc.detail).lower()
            if "maximum size" in detail or "too large" in detail:
                raise AppError("file_too_large", status_code=413) from exc
            raise AppError("invalid_request", status_code=422) from exc

        raise AppError("invalid_request", "表单里没有找到图片文件。", status_code=422)

    read_started_at = perf_counter()
    body = await _read_raw_body_limited(request)
    timing_ms["body_read_ms"] = _elapsed_ms(read_started_at)
    if not body:
        raise AppError("invalid_request", status_code=422)

    save_started_at = perf_counter()
    saved_file = save_upload_bytes(
        body,
        filename=request.headers.get("X-Upload-Filename"),
        content_type=content_type,
    )
    timing_ms["file_save_ms"] = _elapsed_ms(save_started_at)
    return saved_file, timing_ms


def _upload_response(
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


def _create_pending_or_cleanup(db: Session, saved_file: SavedUpload, tenant: Tenant, *, source: str) -> Expense:
    try:
        return create_pending_expense(db, saved_file, tenant.id, source=source, run_enrichment=False)
    except Exception:
        delete_saved_upload(saved_file)
        raise


async def _handle_upload(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant: Tenant,
    db: Session,
    source: str,
    endpoint: str,
) -> UploadResponse:
    started_at = perf_counter()
    saved_file, timing_ms = await _save_request_upload(request)
    db_started_at = perf_counter()
    expense = _create_pending_or_cleanup(db, saved_file, tenant, source=source)
    timing_ms["db_create_ms"] = _elapsed_ms(db_started_at)
    duration_ms = _elapsed_ms(started_at)
    timing_ms["total_ms"] = duration_ms
    logger.info(
        "upload accepted endpoint=%s tenant=%s expense_id=%s bytes=%s media_type=%s duration_ms=%s timing_ms=%s duplicate=%s",
        endpoint,
        tenant.id,
        expense.id,
        saved_file.size_bytes,
        saved_file.media_type,
        duration_ms,
        json.dumps(timing_ms, ensure_ascii=False, sort_keys=True),
        expense.duplicate_status,
    )
    background_tasks.add_task(enrich_pending_expense, expense.id, tenant.id)
    return _upload_response(expense, saved_file, duration_ms, timing_ms)


@router.get(
    "/upload/check",
    response_model=UploadCheckResponse,
)
def upload_check(_: Tenant = Depends(get_current_upload_tenant)) -> UploadCheckResponse:
    settings = get_settings()
    return UploadCheckResponse(
        max_upload_size_mb=settings.max_upload_size_mb,
        supported_file_types=sorted(ALLOWED_EXTENSIONS),
    )


@router.post(
    "/upload-screenshot",
    response_model=UploadResponse,
)
async def upload_screenshot(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant: Tenant = Depends(get_current_upload_tenant),
    db: Session = Depends(get_db),
) -> UploadResponse:
    return await _handle_upload(
        request=request,
        background_tasks=background_tasks,
        tenant=tenant,
        db=db,
        source="iPhone截图",
        endpoint="ios_shortcut",
    )


@router.post(
    "/app/upload-screenshot",
    response_model=UploadResponse,
)
async def app_upload_screenshot(
    request: Request,
    background_tasks: BackgroundTasks,
    tenant: Tenant = Depends(get_current_app_tenant),
    db: Session = Depends(get_db),
) -> UploadResponse:
    return await _handle_upload(
        request=request,
        background_tasks=background_tasks,
        tenant=tenant,
        db=db,
        source="Android截图",
        endpoint="android_app",
    )
