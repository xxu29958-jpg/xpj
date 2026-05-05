from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.auth import verify_upload_token
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.schemas import UploadCheckResponse, UploadResponse
from app.services.expense_service import create_pending_expense
from app.services.file_service import ALLOWED_EXTENSIONS, SavedUpload, save_upload, save_upload_bytes


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
    dependencies=[Depends(verify_upload_token)],
)
def upload_check() -> UploadCheckResponse:
    settings = get_settings()
    return UploadCheckResponse(
        max_upload_size_mb=settings.max_upload_size_mb,
        supported_file_types=sorted(ALLOWED_EXTENSIONS),
    )


@router.post(
    "/upload-screenshot",
    response_model=UploadResponse,
    dependencies=[Depends(verify_upload_token)],
)
async def upload_screenshot(
    request: Request,
    db: Session = Depends(get_db),
) -> UploadResponse:
    saved_file = await _save_request_upload(request)
    expense = create_pending_expense(db, saved_file)
    return UploadResponse(
        id=expense.id,
        public_id=expense.public_id,
        status=expense.status,
        message="uploaded",
    )
