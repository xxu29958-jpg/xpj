from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.auth import get_current_app_tenant, get_current_upload_tenant
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.schemas import UploadCheckResponse, UploadResponse
from app.services.expense_service import create_pending_expense
from app.services.file_service import ALLOWED_EXTENSIONS, SavedUpload, save_upload, save_upload_bytes
from app.tenants import Tenant


router = APIRouter(prefix="/api", tags=["uploads"])

IOS_SHORTCUT_FILE_FIELDS = ("file", "image", "photo", "screenshot")


async def _save_request_upload(request: Request) -> SavedUpload:
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        async with request.form() as form:
            for field_name in IOS_SHORTCUT_FILE_FIELDS:
                value = form.get(field_name)
                if isinstance(value, UploadFile):
                    return await save_upload(value)

            for value in form.values():
                if isinstance(value, UploadFile):
                    return await save_upload(value)

        raise AppError("invalid_request", "表单里没有找到图片文件。", status_code=422)

    body = await request.body()
    if not body:
        raise AppError("invalid_request", status_code=422)

    return save_upload_bytes(
        body,
        filename=request.headers.get("X-Upload-Filename"),
        content_type=content_type,
    )


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
    expense = create_pending_expense(db, saved_file, tenant.id, source="iPhone截图")
    return UploadResponse(
        id=expense.id,
        public_id=expense.public_id,
        status=expense.status,
        message="uploaded",
    )


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
    expense = create_pending_expense(db, saved_file, tenant.id, source="Android截图")
    return UploadResponse(
        id=expense.id,
        public_id=expense.public_id,
        status=expense.status,
        message="uploaded",
    )
