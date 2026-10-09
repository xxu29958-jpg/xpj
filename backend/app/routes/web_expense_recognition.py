"""Resumable Web consumers of the existing text and image recognition commands."""

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.errors import AppError
from app.routes._web_draft_binding import (
    draft_ack_response,
    draft_error_response,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes._web_expense_recognition import recognition_page
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    edit_context_params,
    expense_return_form_context,
    expense_return_query_context,
)
from app.routes._web_session_common import parse_form_row_version_token, resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
)
from app.schemas import ExpenseRecognizeTextRequest
from app.services.expense_ocr_command_service import submit_expense_ocr_retry, submit_expense_text_recognition
from app.services.expense_service import get_expense

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/recognize-text", response_class=HTMLResponse, include_in_schema=False)
@router.get("/expenses/{expense_id}/ocr/retry", response_class=HTMLResponse, include_in_schema=False)
def web_recognition_get(
    request: Request, expense_id: int, ledger_id: str = "",
    return_context: ExpenseReturnContext = Depends(expense_return_query_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return recognition_page(request, db, options, selected, expense_id, return_context.as_kwargs())


def _recognize(db, request, selected, expense_id, fields):
    account_id, device_id = resolve_web_actor(db, request, selected)
    version = parse_form_row_version_token(fields["expected_row_version"])
    if version is None or not fields["idempotency_key"].strip():
        raise AppError("invalid_request", "提交依据无法核对，请保留输入并核对当前账单。", status_code=422)
    common = {"expense_id": expense_id, "tenant_id": selected, "initiator_account_id": account_id,
        "initiator_device_id": device_id, "expected_row_version": version, "idempotency_key": fields["idempotency_key"]}
    if "raw_text" in fields:
        raw = fields["raw_text"]
        if not raw.strip() or len(raw) > 20000:
            raise AppError("invalid_request", "请粘贴 1–20000 字的小票文字。", status_code=422)
        submit_expense_text_recognition(db, **common,
            payload=ExpenseRecognizeTextRequest(expected_row_version=version, raw_text=raw))
    else:
        submit_expense_ocr_retry(db, **common, request_expected_row_version=version)


@router.post("/expenses/{expense_id}/recognize-text", response_class=HTMLResponse, include_in_schema=False)
@router.post("/expenses/{expense_id}/ocr/retry", response_class=HTMLResponse)
def web_recognition_post(
    request: Request, expense_id: int, ledger_id: str = Form(""), raw_text: str = Form(""),
    expected_row_version: str = Form(""), idempotency_key: str = Form(""),
    draft_scope: str = Form(""), draft_ref: str = Form(""), review_latest: bool = Form(False),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    text = request.url.path.endswith("recognize-text")
    fields = {**return_context.as_kwargs(), "ledger_id": ledger_id, "expense_id": str(expense_id),
        "expected_row_version": expected_row_version, "idempotency_key": idempotency_key,
        "draft_ref": draft_ref or str(uuid4()), "draft_scope": draft_scope,
        **({"raw_text": raw_text} if text else {})}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=fields, task="继续原账单的识别请求")
    if retained is not None:
        return retained
    try:
        _require_selected_ledger_write(options, selected)
        fields["draft_scope"] = reviewed_draft_scope(db, request, draft_scope, review=review_latest)
        require_draft_binding(db, request, ledger_id=selected, draft_scope=fields["draft_scope"],
            require_session=False, original_ledger_id=ledger_id)
        if review_latest:
            current = get_expense(db, expense_id, selected)
            if current.status != "pending":
                raise AppError("state_conflict", "账单已离开待确认状态。原识别请求仍保留。", status_code=409)
            fields.update(expected_row_version=str(current.row_version), idempotency_key=str(uuid4()))
            return recognition_page(request, db, options, selected, expense_id, fields, prepared=True)
        _recognize(db, request, selected, expense_id, fields)
    except (AppError, SQLAlchemyError) as exc:
        db.rollback()
        if isinstance(exc, SQLAlchemyError) or exc.status_code >= 500:
            retain_handled_error(request, exc)
        error = exc if isinstance(exc, AppError) else AppError("server_error",
            "暂时未能取得识别结果，请重试原请求。", status_code=503)
        return draft_error_response(request, error) or recognition_page(
            request, db, options, selected, expense_id, fields, error=error)
    next_response = _web_redirect(f"/web/expenses/{expense_id}/edit", selected,
        msg="识别请求已接受；请核对建议后再确认入账。之前未保存的填写仍保留。",
        **edit_context_params(**return_context.as_kwargs()))
    receipt = {"expense_id": expense_id, "operation": "recognize_text" if text else "retry_ocr",
        "accepted": True, "request_key": idempotency_key}
    return draft_ack_response(request, draft_scope=fields["draft_scope"], idempotency_key=idempotency_key,
        receipt=receipt, next_href=next_response.headers["location"]) or next_response
