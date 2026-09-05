"""Web pending-expense read/edit routes and the pending save command."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_confirmed_write_guard import confirmed_write_guard_response
from app.routes._web_expense_edit_command import apply_web_expense_form
from app.routes._web_expense_edit_form import WebExpenseEditForm, web_expense_edit_form
from app.routes._web_expense_fact import web_fact_context
from app.routes._web_expense_helpers import (
    web_edit_context,
    web_save_response,
)
from app.routes._web_expense_return_context import (
    expense_return_query_context,
    resolve_return_to,
    return_context_params,
)
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    fragment: int = 0,
    return_to: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
    flash_type: str = "",
    rev_page: int = Query(default=1, ge=1),
    # A1 P2: 变更记录在同一服务端快照内翻页；缺省 = 重新进入事实页，取新锚。
    rev_snapshot: int | None = Query(default=None, ge=1),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return_context = expense_return_query_context(
        return_to, return_month, return_filter, return_page, return_tag, return_query
    )
    try:
        ctx = web_edit_context(
            db,
            request,
            options,
            selected_id,
            expense_id,
            **return_context.as_kwargs(),
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
    )
    if guarded is not None:
        return guarded
    outcome = apply_web_expense_form(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
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
        **form.return_context.as_kwargs(),
    )
