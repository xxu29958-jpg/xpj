"""Web-session adapters for the existing retained debt-bill owner."""
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import require_draft_binding
from app.routes.web_common import LocalOnly
from app.schemas.debt_bill_capture import (
    DebtBillCaptureListResponse,
    DebtBillCaptureReceipt,
    DebtBillCaptureResponse,
    DebtBillParseOutcome,
    DebtBillParseRequest,
)
from app.services.debt_bill_capture_service import (
    capture_bill,
    capture_response,
    discard_capture,
    get_capture,
    list_captures,
    read_capture_original,
)
from app.services.debt_bill_source_parse import parse_captured_bill, read_parse_outcome
from app.services.file_service import read_upload_bytes
from app.services.image_source_evidence import IMAGE_CONTEXT_HEADER, read_image_context
from app.tenants import AuthContext

router = APIRouter(prefix="/web/debt-bills", tags=["web"])


class WebDebtBillCommand(DebtBillParseRequest):
    ledger_id: str = Field(min_length=1)
    draft_scope: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=64)


def _reader(request: Request, ledger_id: str = Query(min_length=1)) -> AuthContext:
    auth = getattr(request.state, "web_session_auth", None)
    if auth is None:
        raise AppError("invalid_token", status_code=401)
    if ledger_id != auth.ledger_id:
        raise AppError("ledger_forbidden", status_code=403)
    return auth


@router.post("", response_model=DebtBillCaptureReceipt)
async def web_capture_debt_bill(request: Request, file: UploadFile = File(...),
    creation_key: str = Form(min_length=1, max_length=64), idempotency_key: str = Form(min_length=1, max_length=64),
    ledger_id: str = Form(min_length=1), draft_scope: str = Form(min_length=1),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> DebtBillCaptureReceipt:
    auth = require_draft_binding(db, request, ledger_id=ledger_id, draft_scope=draft_scope)
    data = await read_upload_bytes(file)
    context = read_image_context(file.headers.get(IMAGE_CONTEXT_HEADER), data)
    return capture_bill(db, auth=auth, creation_key=creation_key, capture_key=idempotency_key,
        data=data, file_name=file.filename or "debt-bill", media_type=file.content_type, source_context=context)


@router.get("", response_model=DebtBillCaptureListResponse)
def web_debt_bill_captures(creation_key: str = Query(min_length=1, max_length=64),
    auth: AuthContext = Depends(_reader), _local: None = LocalOnly, db: Session = Depends(get_db),
) -> DebtBillCaptureListResponse:
    return DebtBillCaptureListResponse(captures=list_captures(db, tenant_id=auth.ledger_id,
        actor_account_id=auth.account_id, creation_key=creation_key))


@router.get("/by-key/{capture_key}", response_model=DebtBillCaptureResponse)
def web_debt_bill_by_key(capture_key: str, auth: AuthContext = Depends(_reader),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> DebtBillCaptureResponse:
    return capture_response(get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id,
        capture_key=capture_key))


@router.get("/{public_id}", response_model=DebtBillCaptureResponse)
def web_debt_bill_detail(public_id: str, auth: AuthContext = Depends(_reader),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> DebtBillCaptureResponse:
    return capture_response(get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id))


@router.get("/{public_id}/original", response_class=FileResponse)
def web_debt_bill_original(public_id: str, auth: AuthContext = Depends(_reader),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> FileResponse:
    source = get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id)
    original = read_capture_original(source)
    return FileResponse(original.path, media_type=original.media_type,
        headers={"Cache-Control": "private, no-store"}, background=BackgroundTask(original.close))


@router.post("/{public_id}/parse", response_model=DebtBillParseOutcome)
def web_parse_debt_bill(request: Request, public_id: str, payload: WebDebtBillCommand,
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> DebtBillParseOutcome:
    auth = require_draft_binding(db, request, ledger_id=payload.ledger_id, draft_scope=payload.draft_scope)
    return parse_captured_bill(db, auth=auth, public_id=public_id,
        expected_row_version=payload.expected_row_version, key=payload.idempotency_key)


@router.get("/{public_id}/parse-attempts/{attempt_key}", response_model=DebtBillParseOutcome)
def web_debt_bill_parse_outcome(public_id: str, attempt_key: str, auth: AuthContext = Depends(_reader),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> DebtBillParseOutcome:
    return read_parse_outcome(db, auth=auth, public_id=public_id, key=attempt_key)


@router.post("/{public_id}/discard", response_model=DebtBillCaptureResponse)
def web_discard_debt_bill(request: Request, public_id: str, payload: WebDebtBillCommand,
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> DebtBillCaptureResponse:
    auth = require_draft_binding(db, request, ledger_id=payload.ledger_id, draft_scope=payload.draft_scope)
    return discard_capture(db, auth=auth, public_id=public_id,
        expected_row_version=payload.expected_row_version, key=payload.idempotency_key)
