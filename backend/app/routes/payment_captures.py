"""Personal notification evidence and explicit review of uncertain candidates."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas.payment_capture import PaymentCaptureCreate, PaymentCaptureDecision, PaymentCaptureResponse
from app.services.payment_capture_commands import decide_capture
from app.services.payment_capture_identity import capture_response, list_review_captures, require_capture
from app.services.payment_capture_service import capture_notification
from app.tenants import AuthContext

router = APIRouter(prefix="/api/payment-captures", tags=["payment-captures"])


@router.get("", response_model=list[PaymentCaptureResponse])
def list_captures(auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    return list_review_captures(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id)


@router.post("", response_model=PaymentCaptureResponse, status_code=201)
def capture(payload: PaymentCaptureCreate, auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return capture_notification(db, auth=auth, payload=payload)


@router.get("/{public_id}", response_model=PaymentCaptureResponse)
def detail(public_id: str, auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    return capture_response(db, require_capture(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id))


@router.post("/{public_id}/decision", response_model=PaymentCaptureResponse)
def decide(public_id: str, payload: PaymentCaptureDecision,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return decide_capture(db, auth=auth, public_id=public_id, payload=payload, idempotency_key=idempotency_key)
