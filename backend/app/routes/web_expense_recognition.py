"""Paste receipt text without replacing the bill editor or its unsaved inputs."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.errors import AppError
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    edit_context_params,
    expense_return_form_context,
)
from app.routes._web_session_common import parse_form_row_version_token, resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    _with_ledger,
    preserve_original_ledger_form,
    templates,
)
from app.schemas import ExpenseRecognizeTextRequest
from app.services.expense_ocr_command_service import submit_expense_text_recognition

router = APIRouter(prefix="/web", tags=["web"])


def _text_page(request, db, options, selected, expense_id, fields, *, error="", status=200, editable=True, retry_allowed=False):
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected)
    ctx.update(original_fields=fields, error=error, text_editable=editable,
        can_submit=editable or retry_allowed,
        current_href=_with_ledger(f"/web/expenses/{expense_id}/edit", selected,
            **edit_context_params(**{name: fields.get(name, "") for name in ExpenseReturnContext().as_kwargs()})))
    return templates.TemplateResponse(request=request, name="expense_text_recognition.html", context=ctx,
        status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/expenses/{expense_id}/recognize-text", response_class=HTMLResponse, include_in_schema=False)
def web_text_recognition_post(
    request: Request, expense_id: int, ledger_id: str = Form(""), raw_text: str = Form(""),
    expected_row_version: str = Form(""), idempotency_key: str = Form(""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    fields = {**return_context.as_kwargs(), "ledger_id": ledger_id, "raw_text": raw_text,
        "expected_row_version": expected_row_version, "idempotency_key": idempotency_key}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=fields, task="继续原账单的文字识别请求")
    if retained is not None:
        return retained
    try:
        _require_selected_ledger_write(options, selected)
        account_id, device_id = resolve_web_actor(db, request, selected)
        version = parse_form_row_version_token(expected_row_version)
        if version is None or not idempotency_key.strip():
            raise AppError("invalid_request", "请从原账单页面发起文字识别。", status_code=422)
        if not raw_text.strip() or len(raw_text) > 20000:
            return _text_page(request, db, options, selected, expense_id, fields,
                error="请粘贴 1–20000 字的小票文字。", status=422)
        submit_expense_text_recognition(db, expense_id=expense_id, tenant_id=selected,
            initiator_account_id=account_id, initiator_device_id=device_id,
            payload=ExpenseRecognizeTextRequest(expected_row_version=version, raw_text=raw_text),
            expected_row_version=version, idempotency_key=idempotency_key)
    except (AppError, SQLAlchemyError) as exc:
        db.rollback()
        status = exc.status_code if isinstance(exc, AppError) else 503
        if status >= 500:
            retain_handled_error(request, exc)
        message = exc.message if isinstance(exc, AppError) else "暂时未能取得识别结果，请重试原请求。"
        retry_allowed = status >= 500 or status == 429 or (isinstance(exc, AppError) and exc.error == "idempotency_key_in_progress")
        return _text_page(request, db, options, selected, expense_id, fields,
            error=message, status=status, editable=False, retry_allowed=retry_allowed)
    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected,
        msg="文字识别请求已接受；请核对提取结果，再确认入账。原窗口未保存的填写仍保留。",
        **edit_context_params(**return_context.as_kwargs()))
