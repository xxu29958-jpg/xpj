from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.auth import verify_upload_token
from app.database import get_db
from app.schemas import UploadResponse
from app.services.expense_service import create_pending_expense
from app.services.file_service import save_upload


router = APIRouter(prefix="/api", tags=["uploads"])


@router.post(
    "/upload-screenshot",
    response_model=UploadResponse,
    dependencies=[Depends(verify_upload_token)],
)
async def upload_screenshot(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadResponse:
    saved_file = await save_upload(file)
    expense = create_pending_expense(db, saved_file)
    return UploadResponse(id=expense.id, status=expense.status, message="uploaded")
