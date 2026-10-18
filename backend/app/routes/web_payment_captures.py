"""Browser review consumes the same capture command and identity as Android."""

from fastapi import APIRouter, Depends, Form, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.errors import AppError
from app.routes._web_debt_repayment import require_repayment_binding
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
)
from app.routes.web_repayment_drafts import _render_repayment_drafts
from app.schemas.payment_capture import PaymentCaptureDecision
from app.services.exchange_rate_service import amount_major_to_minor
from app.services.payment_capture_commands import decide_capture

router = APIRouter(prefix="/web/payment-captures", tags=["web"])


@router.post("/{public_id}/decision")
def review_capture(request: Request, public_id: str, ledger_id: str = Form(), origin_binding: str = Form(),
        capture_public_id: str = Form(), expected_row_version: int = Form(), original_currency: str = Form(),
        kind: str = Form(), original_amount: str = Form(default=""), reason: str = Form(default=""),
        idempotency_key: str = Form(), csrf_token: str = Form(default=""),
        _local: None = LocalOnly, db: Session = Depends(get_db)):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    values = {"capture_public_id": capture_public_id, "ledger_id": ledger_id, "origin_binding": origin_binding,
        "expected_row_version": expected_row_version, "original_currency": original_currency, "kind": kind,
        "original_amount": original_amount, "reason": reason, "idempotency_key": idempotency_key}
    try:
        require_repayment_binding(request, db, values=values, public_id=public_id, target_field="capture_public_id")
        _require_selected_ledger_write(options, selected_id)
        auth = getattr(request.state, "web_session_auth", None)
        if auth is None or auth.tenant_id != selected_id:
            raise AppError("session_binding_changed", "当前身份或账本已变化，请回到原账号和账本处理。", status_code=409)
        payload = PaymentCaptureDecision(expected_row_version=expected_row_version, kind=kind,
            original_currency=original_currency, reason=reason,
            original_amount_minor=None if kind == "dismissed" else amount_major_to_minor(original_amount, original_currency))
        receipt = decide_capture(db, auth=auth, public_id=public_id, payload=payload, idempotency_key=idempotency_key)
    except (AppError, ValidationError, SQLAlchemyError, ValueError) as exc:
        retain_handled_error(request, exc)
        db.rollback()
        return _render_repayment_drafts(request, db, options=options, selected_id=selected_id, capture_values=values,
            status_code=exc.status_code if isinstance(exc, AppError) else 422 if isinstance(exc, (ValueError, ValidationError)) else 503,
            form_error=exc.message if isinstance(exc, AppError) else "处理未确认，输入保留，请核对后重试。")
    return _render_repayment_drafts(request, db, options=options, selected_id=selected_id, capture_result=receipt)
