"""Personal repayment captures: persistent original review and processed history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_repayment_review import _audit_row_view, render_review, submit_review
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.routes.web_debts import _web_viewer_account_id
from app.services.debt_service import (
    list_repayment_draft_audit_for_account,
)

router = APIRouter(prefix="/web/repayment-drafts", tags=["web"])

_AUDIT_INTRO = "手机自动捕获的还款通知在这里复核：确认记到哪笔欠款，或忽略。重复提交不会记成两笔。"
_EMPTY_TITLE = "还没有还款捕获"
_EMPTY_BODY = "手机 App 自动捕获的还款通知会在这里出现；打开原采集可核对金额、选择欠款或忽略。"



def _actor_account_id(request: Request, db: Session, ledger_id: str) -> int:
    account_id = _web_viewer_account_id(request, db, ledger_id)
    if account_id is None:
        raise AppError("permission_denied", "当前账本没有可写入的账户。", status_code=403)
    return account_id


def _render_repayment_drafts(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    form_error: str | None = None,
    error_draft_public_id: str | None = None,
    flash_message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    account_id = _web_viewer_account_id(request, db, selected_id)
    rows = (
        list_repayment_draft_audit_for_account(db, account_id=account_id, tenant_id=selected_id)
        if account_id is not None
        else []
    )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="还款捕获",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _AUDIT_INTRO
    ctx["rows"] = [_audit_row_view(row) for row in rows]
    ctx["empty_title"] = _EMPTY_TITLE
    ctx["empty_body"] = _EMPTY_BODY
    ctx["form_error"] = form_error
    ctx["error_draft_public_id"] = error_draft_public_id
    ctx["flash_message"] = flash_message
    return templates.TemplateResponse(
        request=request,
        name="repayment_drafts.html",
        context=ctx,
        status_code=status_code,
    )



@router.get("", response_class=HTMLResponse)
def web_repayment_drafts(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
    flash_message: str | None = None,
    form_error: str | None = None,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _render_repayment_drafts(
        request,
        db,
        options=options,
        selected_id=selected_id,
        flash_message=flash_message,
        form_error=form_error,
    )


@router.get("/{public_id}", response_class=HTMLResponse)
def web_repayment_review(
    request: Request, public_id: str, ledger_id: str | None = None,
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return render_review(request, db, options=options, selected_id=selected_id, public_id=public_id,
        account_id=_actor_account_id(request, db, selected_id))


@router.post("/{public_id}/review", response_class=HTMLResponse)
def web_submit_repayment_review(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), draft_public_id: str = Form(default=""),
    origin_binding: str = Form(default=""), review_action: str = Form(default=""),
    target_with_expected_row_version: str = Form(default=""), original_currency: str = Form(default=""),
    original_amount: str = Form(default=""), idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""), _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    values = {"draft_public_id": draft_public_id, "ledger_id": ledger_id, "origin_binding": origin_binding,
        "review_action": review_action, "target_with_expected_row_version": target_with_expected_row_version, "original_currency": original_currency,
        "original_amount": original_amount, "idempotency_key": idempotency_key}
    return submit_review(request, db, options=options, selected_id=selected_id, public_id=public_id,
        account_id=_actor_account_id(request, db, selected_id), values=values)
