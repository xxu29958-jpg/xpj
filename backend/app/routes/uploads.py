from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_current_app_tenant, get_current_upload_tenant
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.models import Expense
from app.schemas import UploadCheckResponse, UploadResponse
from app.services.expense_service import create_pending_expense
from app.services.file_service import ALLOWED_EXTENSIONS, SavedUpload, delete_saved_upload, save_upload, save_upload_bytes
from app.tenants import Tenant


router = APIRouter(prefix="/api", tags=["uploads"])

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


async def _save_request_upload(request: Request) -> SavedUpload:
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        try:
            form_context = request.form(
                max_files=4,
                max_fields=12,
                max_part_size=get_settings().max_upload_size_bytes,
            )
            async with form_context as form:
                for field_name in IOS_SHORTCUT_FILE_FIELDS:
                    value = form.get(field_name)
                    if isinstance(value, UploadFile):
                        return await save_upload(value)

                for value in form.values():
                    if isinstance(value, UploadFile):
                        return await save_upload(value)
        except StarletteHTTPException as exc:
            detail = str(exc.detail).lower()
            if "maximum size" in detail or "too large" in detail:
                raise AppError("file_too_large", status_code=413) from exc
            raise AppError("invalid_request", status_code=422) from exc

        raise AppError("invalid_request", "表单里没有找到图片文件。", status_code=422)

    body = await _read_raw_body_limited(request)
    if not body:
        raise AppError("invalid_request", status_code=422)

    return save_upload_bytes(
        body,
        filename=request.headers.get("X-Upload-Filename"),
        content_type=content_type,
    )


def _upload_response(expense: Expense) -> UploadResponse:
    return UploadResponse(
        id=expense.id,
        public_id=expense.public_id,
        status=expense.status,
        message="uploaded",
        image_hash=expense.image_hash or "",
        thumbnail_path=expense.thumbnail_path,
        duplicate_status=expense.duplicate_status,
        duplicate_of_id=expense.duplicate_of_id,
    )


def _create_pending_or_cleanup(db: Session, saved_file: SavedUpload, tenant: Tenant, *, source: str) -> Expense:
    try:
        return create_pending_expense(db, saved_file, tenant.id, source=source)
    except Exception:
        delete_saved_upload(saved_file)
        raise


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
    tenant: Tenant = Depends(get_current_upload_tenant),
    db: Session = Depends(get_db),
) -> UploadResponse:
    saved_file = await _save_request_upload(request)
    expense = _create_pending_or_cleanup(db, saved_file, tenant, source="iPhone截图")
    return _upload_response(expense)


@router.post(
    "/app/upload-screenshot",
    response_model=UploadResponse,
)
async def app_upload_screenshot(
    request: Request,
    tenant: Tenant = Depends(get_current_app_tenant),
    db: Session = Depends(get_db),
) -> UploadResponse:
    saved_file = await _save_request_upload(request)
    expense = _create_pending_or_cleanup(db, saved_file, tenant, source="Android截图")
    return _upload_response(expense)
