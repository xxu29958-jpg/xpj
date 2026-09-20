"""Authenticated observations and continuation for a bill's original."""

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.routes._upload_request import read_request_upload
from app.schemas._original_attachment import (
    OriginalCleanupRequest,
    OriginalCommandReceipt,
    OriginalHealthResponse,
    OriginalReplenishmentRequest,
    OriginalVerificationRequest,
)
from app.services.original_command_service import continue_original_cleanup, replenish_original, verify_original
from app.services.original_health_service import inspect_expense_original
from app.tenants import AuthContext

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


@router.get("/{expense_id}/original", response_model=OriginalHealthResponse)
def get_original_health(expense_id: int, auth: AuthContext = Depends(get_current_app_context),
                        db: Session = Depends(get_db)) -> OriginalHealthResponse:
    return inspect_expense_original(db, expense_id=expense_id, tenant_id=auth.tenant_id)


@router.post("/{expense_id}/original/verify", response_model=OriginalCommandReceipt)
def post_original_verification(expense_id: int, payload: OriginalVerificationRequest,
                               idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=64),
                               auth: AuthContext = Depends(get_current_writer_context),
                               db: Session = Depends(get_db)) -> OriginalCommandReceipt:
    return verify_original(db, expense_id=expense_id, auth=auth, payload=payload, idempotency_key=idempotency_key)


@router.post("/{expense_id}/original/replenish", response_model=OriginalCommandReceipt,
    openapi_extra={"requestBody": {"required": True, "content": {
        "multipart/form-data": {"schema": {"type": "object", "required": ["file"],
            "properties": {"file": {"type": "string", "format": "binary"}}}},
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    }}})
async def post_original_replenishment(request: Request, expense_id: int,
                                      expected_row_version: int = Query(gt=0),
                                      expected_sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
                                      idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=64),
                                      auth: AuthContext = Depends(get_current_writer_context),
                                      db: Session = Depends(get_db)) -> OriginalCommandReceipt:
    content, _timing = await read_request_upload(request)
    return replenish_original(db, expense_id=expense_id, auth=auth,
        payload=OriginalReplenishmentRequest(expected_row_version=expected_row_version, expected_sha256=expected_sha256),
        data=content.data, filename=content.filename, content_type=content.content_type, idempotency_key=idempotency_key)


@router.post("/{expense_id}/original/cleanup/retry", response_model=OriginalCommandReceipt)
def post_original_cleanup_retry(expense_id: int, payload: OriginalCleanupRequest,
                                 idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=64),
                                 auth: AuthContext = Depends(get_current_writer_context),
                                 db: Session = Depends(get_db)) -> OriginalCommandReceipt:
    return continue_original_cleanup(db, expense_id=expense_id, auth=auth, payload=payload,
        cancel_remaining=False, idempotency_key=idempotency_key)


@router.post("/{expense_id}/original/cleanup/cancel", response_model=OriginalCommandReceipt)
def post_original_cleanup_cancel(expense_id: int, payload: OriginalCleanupRequest,
                                  idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=64),
                                  auth: AuthContext = Depends(get_current_writer_context),
                                  db: Session = Depends(get_db)) -> OriginalCommandReceipt:
    return continue_original_cleanup(db, expense_id=expense_id, auth=auth, payload=payload,
        cancel_remaining=True, idempotency_key=idempotency_key)
