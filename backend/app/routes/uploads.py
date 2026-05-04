from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from app.auth import verify_upload_token
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.schemas import UploadCheckResponse, UploadResponse
from app.services.expense_service import create_pending_expense
from app.services.file_service import ALLOWED_EXTENSIONS, save_upload, save_upload_bytes


router = APIRouter(prefix="/api", tags=["uploads"])


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
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> UploadResponse:
    if file is not None:
        saved_file = await save_upload(file)
    else:
        body = await request.body()
        if not body:
            raise AppError("invalid_request", status_code=422)
        saved_file = save_upload_bytes(
            body,
            filename=request.headers.get("X-Upload-Filename"),
            content_type=request.headers.get("content-type"),
        )

    expense = create_pending_expense(db, saved_file)
    return UploadResponse(id=expense.id, status=expense.status, message="uploaded")
