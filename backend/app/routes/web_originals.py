"""Same-bill original inspection and native continuations; commands stay in services."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.routes._upload_request import read_request_upload
from app.routes._web_attachment_intent import (
    attachment_ack_response,
    attachment_form_context,
    require_attachment_binding,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas._original_attachment import (
    OriginalCleanupRequest,
    OriginalCommandReceipt,
    OriginalReplenishmentRequest,
    OriginalVerificationRequest,
)
from app.services.expense_query import get_expense
from app.services.original_command_service import continue_original_cleanup, replenish_original, verify_original
from app.services.original_health_service import inspect_expense_original

router = APIRouter(prefix="/web", tags=["web"])


def _writer(db, request, ledger_id, draft_scope):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    _require_selected_ledger_write(options, selected)
    return require_attachment_binding(db, request, ledger_id=ledger_id, draft_scope=draft_scope)


def _accepted(request, receipt: OriginalCommandReceipt, *, ledger_id, draft_scope, idempotency_key):
    redirect = _web_redirect(f"/web/expenses/{receipt.expense_id}/original", ledger_id, msg="原件操作已接受。下方为重新检查结果。")
    return attachment_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=receipt.model_dump(mode="json"), next_href=redirect.headers["location"]) or redirect


@router.get("/originals", response_class=HTMLResponse, include_in_schema=False)
def web_originals(request: Request, ledger_id: str | None = None, after: int = Query(default=0, ge=0),
                  _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    # Only references for this page; bytes are inspected solely by an explicit action.
    rows = list(db.scalars(ledger_scoped_select(Expense, selected).where(Expense.id > after)
                          .order_by(Expense.id).limit(26)))
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="原件检查")
    ctx.update(original_rows=rows[:25], next_after=rows[24].id if len(rows) > 25 else None)
    return templates.TemplateResponse(request=request, name="originals.html", context=ctx)


@router.get("/expenses/{expense_id}/original/health", include_in_schema=False)
def web_original_health(request: Request, expense_id: int, ledger_id: str | None = None,
                        _local: None = LocalOnly, db: Session = Depends(get_db)) -> JSONResponse:
    selected = _resolve_selected_ledger_id(db, ledger_id, request=request)
    health = inspect_expense_original(db, expense_id=expense_id, tenant_id=selected)
    return JSONResponse(health.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.get("/expenses/{expense_id}/original", response_class=HTMLResponse, include_in_schema=False)
def web_original(request: Request, expense_id: int, ledger_id: str | None = None,
                  _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    expense = get_expense(db, expense_id, selected)
    health = inspect_expense_original(db, expense_id=expense_id, tenant_id=selected)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="账单原件")
    root = f"/web/expenses/{expense_id}/original"
    intents = {action: attachment_form_context(db, request, action=f"{root}/{action}", ledger_id=selected)
               for action in ("verify", "replenish", "cleanup/retry", "cleanup/cancel")}
    ctx.update(original=health, original_expense=expense, original_intents=intents,
               message=request.query_params.get("msg", ""))
    return templates.TemplateResponse(request=request, name="original.html", context=ctx)


@router.post("/expenses/{expense_id}/original/verify", include_in_schema=False)
def web_original_verify(request: Request, expense_id: int, expected_row_version: int = Query(gt=0),
                         ledger_id: str = Query(), draft_scope: str = Query(max_length=2048),
                         idempotency_key: str = Query(min_length=1, max_length=64),
                         reviewed_sha256: str = Form(pattern=r"^[0-9a-f]{64}$"),
                         _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    auth = _writer(db, request, ledger_id, draft_scope)
    receipt = verify_original(db, expense_id=expense_id, auth=auth,
        payload=OriginalVerificationRequest(expected_row_version=expected_row_version, reviewed_sha256=reviewed_sha256),
        idempotency_key=idempotency_key)
    return _accepted(request, receipt, ledger_id=ledger_id, draft_scope=draft_scope, idempotency_key=idempotency_key)


@router.post("/expenses/{expense_id}/original/replenish", include_in_schema=False)
async def web_original_replenish(request: Request, expense_id: int, expected_row_version: int = Query(gt=0),
                                 expected_sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
                                 ledger_id: str = Query(), draft_scope: str = Query(max_length=2048),
                                 idempotency_key: str = Query(min_length=1, max_length=64),
                                 _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    auth = _writer(db, request, ledger_id, draft_scope)
    content, _timing = await read_request_upload(request)
    receipt = replenish_original(db, expense_id=expense_id, auth=auth,
        payload=OriginalReplenishmentRequest(expected_row_version=expected_row_version, expected_sha256=expected_sha256),
        data=content.data, filename=content.filename, content_type=content.content_type, idempotency_key=idempotency_key)
    return _accepted(request, receipt, ledger_id=ledger_id, draft_scope=draft_scope, idempotency_key=idempotency_key)


@router.post("/expenses/{expense_id}/original/cleanup/retry", include_in_schema=False)
def web_original_cleanup_retry(request: Request, expense_id: int, expected_row_version: int = Query(gt=0),
                                ledger_id: str = Query(), draft_scope: str = Query(max_length=2048),
                                idempotency_key: str = Query(min_length=1, max_length=64), request_id: UUID = Form(),
                                _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    auth = _writer(db, request, ledger_id, draft_scope)
    receipt = continue_original_cleanup(db, expense_id=expense_id, auth=auth,
        payload=OriginalCleanupRequest(expected_row_version=expected_row_version, request_id=request_id),
        cancel_remaining=False, idempotency_key=idempotency_key)
    return _accepted(request, receipt, ledger_id=ledger_id, draft_scope=draft_scope, idempotency_key=idempotency_key)


@router.post("/expenses/{expense_id}/original/cleanup/cancel", include_in_schema=False)
def web_original_cleanup_cancel(request: Request, expense_id: int, expected_row_version: int = Query(gt=0),
                                 ledger_id: str = Query(), draft_scope: str = Query(max_length=2048),
                                 idempotency_key: str = Query(min_length=1, max_length=64), request_id: UUID = Form(),
                                 _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    auth = _writer(db, request, ledger_id, draft_scope)
    receipt = continue_original_cleanup(db, expense_id=expense_id, auth=auth,
        payload=OriginalCleanupRequest(expected_row_version=expected_row_version, request_id=request_id),
        cancel_remaining=True, idempotency_key=idempotency_key)
    return _accepted(request, receipt, ledger_id=ledger_id, draft_scope=draft_scope, idempotency_key=idempotency_key)
