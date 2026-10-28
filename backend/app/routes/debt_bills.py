"""Private retained debt-bill originals and explicit synchronous suggestions."""

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.auth import get_current_app_context, get_current_protocol_writer_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import DebtBillParseResponse
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

router = APIRouter(tags=["debts"])


@router.post("/api/debts/parse-bill", response_model=DebtBillParseResponse)
def post_parse_debt_bill(auth: AuthContext = Depends(get_current_writer_context)) -> DebtBillParseResponse:
    """Old transient requests have no retained original; never silently accept them."""
    raise AppError("client_upgrade_required", status_code=409)


@router.post("/api/debt-bills", response_model=DebtBillCaptureReceipt)
async def post_capture_bill(file: UploadFile = File(...), creation_key: str = Form(min_length=1, max_length=64),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=64),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db),
) -> DebtBillCaptureReceipt:
    data = await read_upload_bytes(file)
    context = read_image_context(file.headers.get(IMAGE_CONTEXT_HEADER), data)
    return capture_bill(db, auth=auth, creation_key=creation_key, capture_key=idempotency_key,
        data=data, file_name=file.filename or "debt-bill", media_type=file.content_type, source_context=context)


@router.get("/api/debt-bills", response_model=DebtBillCaptureListResponse)
def get_captures(creation_key: str | None = Query(default=None, min_length=1, max_length=64),
    debt_public_id: str | None = Query(default=None, min_length=1, max_length=36),
    auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db),
) -> DebtBillCaptureListResponse:
    return DebtBillCaptureListResponse(captures=list_captures(db, tenant_id=auth.ledger_id,
        actor_account_id=auth.account_id, creation_key=creation_key, debt_public_id=debt_public_id))


@router.get("/api/debt-bills/by-key/{capture_key}", response_model=DebtBillCaptureResponse)
def get_capture_by_key(capture_key: str, auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtBillCaptureResponse:
    return capture_response(get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id,
                                        capture_key=capture_key))


@router.get("/api/debt-bills/{public_id}", response_model=DebtBillCaptureResponse)
def get_capture_detail(public_id: str, auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtBillCaptureResponse:
    return capture_response(get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id,
                                        public_id=public_id))


@router.get("/api/debt-bills/{public_id}/original", response_class=FileResponse)
def get_capture_image(public_id: str, auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> FileResponse:
    source = get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id)
    snapshot = read_capture_original(source)
    return FileResponse(snapshot.path, media_type=snapshot.media_type,
        headers={"Cache-Control": "private, no-store"}, background=BackgroundTask(snapshot.close))


@router.post("/api/debt-bills/{public_id}/parse", response_model=DebtBillParseOutcome)
def post_parse_capture(public_id: str, payload: DebtBillParseRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=64),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db),
) -> DebtBillParseOutcome:
    return parse_captured_bill(db, auth=auth, public_id=public_id,
        expected_row_version=payload.expected_row_version, key=idempotency_key)


@router.get("/api/debt-bills/{public_id}/parse-attempts/{attempt_key}", response_model=DebtBillParseOutcome)
def get_parse_attempt(public_id: str, attempt_key: str,
    auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db),
) -> DebtBillParseOutcome:
    return read_parse_outcome(db, auth=auth, public_id=public_id, key=attempt_key)


@router.post("/api/debt-bills/{public_id}/discard", response_model=DebtBillCaptureResponse)
def post_discard_capture(public_id: str, payload: DebtBillParseRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=64),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db),
) -> DebtBillCaptureResponse:
    return discard_capture(db, auth=auth, public_id=public_id,
        expected_row_version=payload.expected_row_version, key=idempotency_key)
