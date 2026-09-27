"""Web pending-expense read/edit routes and the pending save command."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_confirmed_write_guard import confirmed_write_guard_response
from app.routes._web_expense_edit_command import apply_web_expense_form
from app.routes._web_expense_edit_form import WebExpenseEditForm, web_expense_edit_form
from app.routes._web_expense_fact import web_fact_context
from app.routes._web_expense_fx import render_web_fx_action
from app.routes._web_expense_helpers import (
    web_edit_context,
    web_save_response,
)
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    edit_context_params,
    expense_return_form_context,
    expense_return_query_context,
    resolve_return_to,
    return_context_params,
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
from app.services.expense_ocr_command_service import submit_expense_ocr_retry

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    fragment: int = 0,
    return_context: ExpenseReturnContext = Depends(expense_return_query_context),
    flash_type: str = "",
    rev_page: int = Query(default=1, ge=1),
    # A1 P2: 变更记录在同一服务端快照内翻页；缺省 = 重新进入事实页，取新锚。
    rev_snapshot: int | None = Query(default=None, ge=1),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    try:
        ctx = web_edit_context(
            db,
            request,
            options,
            selected_id,
            expense_id,
            return_context=return_context,
        )
    except AppError as exc:
        # A deleted / cross-ledger expense (stale link, switched ledger) must
        # not surface as a bare-JSON page — or, for the drawer fetch, as raw
        # JSON injected into the drawer (desktop.js does not check res.ok).
        if fragment:
            return HTMLResponse(
                f'<div class="empty-cell">{exc.message}</div>',
                status_code=exc.status_code,
            )
        return _web_redirect(
            resolve_return_to(return_context.return_to, "/web/confirmed"),
            selected_id,
            msg=exc.message,
            flash_type="error",
            **return_context_params(**return_context.as_kwargs()),
        )
    # A1: confirmed 账单落地页 = read-first 事实详情（更正走显式命令）；
    # pending 保持原编辑表单。抽屉只服务待确认队列，confirmed 的 fragment
    # 请求给一个只读指引片段，不渲染可写表单。
    if ctx["expense"]["status"] == "confirmed":
        if fragment:
            return HTMLResponse(
                '<div class="empty-cell">这笔账单已确认：请在完整页面查看事实与变更记录，'
                "需要修改请使用「更正这笔账单」。</div>"
            )
        fact_ctx = web_fact_context(
            db,
            request,
            options,
            selected_id,
            expense_id,
            revision_page=rev_page,
            revision_snapshot=rev_snapshot,
            flash_type=flash_type,
            return_context=return_context,
        )
        return templates.TemplateResponse(request=request, name="expense_fact.html", context=fact_ctx)
    # ?fragment=1 returns the drawer fragment fetched by desktop.js.
    if fragment:
        return templates.TemplateResponse(request=request, name="_edit_drawer.html", context=ctx)
    return templates.TemplateResponse(request=request, name="edit.html", context=ctx)


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    form: WebExpenseEditForm = Depends(web_expense_edit_form),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db, form.ledger_id or None, options, request=request
    )
    _require_selected_ledger_write(options, selected_id)
    guarded = confirmed_write_guard_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        error_code="expense_correction_required",
        fragment=bool(form.fragment),
        return_context=form.return_context,
    )
    if guarded is not None:
        return guarded
    account_id, device_id = resolve_web_actor(db, request, selected_id)
    outcome = apply_web_expense_form(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
        initiator_account_id=account_id,
        initiator_device_id=device_id,
        form=form,
    )
    return web_save_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        error=outcome.error,
        error_status=outcome.error_status,
        form_values=outcome.form_values,
        field_errors=outcome.field_errors,
        conflict=outcome.conflict,
        fragment=form.fragment,
        return_context=form.return_context,
    )


@router.post("/expenses/{expense_id}/fx", response_class=HTMLResponse)
def web_request_expense_fx(
    expense_id: int, request: Request, form: WebExpenseEditForm = Depends(web_expense_edit_form),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    return render_web_fx_action(db, request, expense_id, form, start=True)


@router.post("/expenses/{expense_id}/fx-status", response_class=HTMLResponse)
def web_refresh_expense_fx(
    expense_id: int, request: Request, form: WebExpenseEditForm = Depends(web_expense_edit_form),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    return render_web_fx_action(db, request, expense_id, form, start=False)


@router.post("/expenses/{expense_id}/ocr/retry", response_class=HTMLResponse)
def web_retry_expense_ocr(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    fields = {**return_context.as_kwargs(), "ledger_id": ledger_id,
        "expected_row_version": expected_row_version, "idempotency_key": idempotency_key}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=fields, task="继续原账单的识别请求")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    account_id, device_id = resolve_web_actor(db, request, selected)
    origin = edit_context_params(**return_context.as_kwargs())
    try:
        version = parse_form_row_version_token(expected_row_version)
        if version is None or not idempotency_key.strip():
            raise AppError("invalid_request", "请从原账单页面发起识别。", status_code=422)
        submit_expense_ocr_retry(db, expense_id=expense_id, tenant_id=selected,
            initiator_account_id=account_id, initiator_device_id=device_id,
            expected_row_version=version, request_expected_row_version=version,
            idempotency_key=idempotency_key)
    except AppError as exc:
        db.rollback()
        ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected)
        ctx.update(error=exc.message, original_fields=fields,
            can_retry=exc.status_code >= 500 or exc.error == "idempotency_key_in_progress",
            current_href=_with_ledger(f"/web/expenses/{expense_id}/edit", selected, **origin),
            original_href=_with_ledger(f"/web/expenses/{expense_id}/original", selected))
        return templates.TemplateResponse(request=request, name="expense_ocr_retry.html", context=ctx,
            status_code=exc.status_code, headers={"Cache-Control": "no-store"})
    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected,
        msg="识别请求已接受；请核对当前账单，仍缺少的字段可手动补全。原窗口未保存的填写仍保留。",
        **origin)
