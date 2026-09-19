"""Authenticated observations and continuation for a bill's original."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas._original_attachment import OriginalCommandReceipt, OriginalHealthResponse, OriginalVerificationRequest
from app.services.original_command_service import verify_original
from app.services.original_health_service import inspect_expense_original
from app.tenants import AuthContext

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


@router.get("/{expense_id}/original", response_model=OriginalHealthResponse)
def get_original_health(expense_id: int, auth: AuthContext = Depends(get_current_app_context),
                        db: Session = Depends(get_db)) -> OriginalHealthResponse:
    return inspect_expense_original(db, expense_id=expense_id, tenant_id=auth.tenant_id)


@router.post("/{expense_id}/original/verify", response_model=OriginalCommandReceipt)
def post_original_verification(expense_id: int, payload: OriginalVerificationRequest,
                               idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
                               auth: AuthContext = Depends(get_current_writer_context),
                               db: Session = Depends(get_db)) -> OriginalCommandReceipt:
    return verify_original(db, expense_id=expense_id, auth=auth, payload=payload, idempotency_key=idempotency_key)
