"""/web expense edit / save / confirm / reject — expense 主体 routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_edit_command import (
    WebExpenseConfirmOutcome,
    apply_web_expense_form,
    prepare_web_expense_form,
)
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_expense_helpers import (
    confirm_reject_error,
    drawer_fragment_ok,
    web_edit_context,
    web_save_response,
)
from app.routes._web_expense_return_context import (
    resolve_return_to,
    return_context_params,
)
from app.routes.web_bill_split import build_split_invite_context
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.services.expense_review_command_service import confirm_expense_submission
from app.services.expense_service import (
    reject_expense,
    undo_reject_expense,
    update_expense,
)

router = APIRouter(prefix="/web", tags=["web"])
_ROTATE_IDEMPOTENCY_ERRORS = frozenset(
    {"idempotency_key_required", "idempotency_key_reused"}
)


def confirm_web_expense(
    db: Session,
    *,
    expense_id: int,
    selected_ledger_id: str,
    expected_row_version: str,
    idempotency_key: str,
    save_before_confirm: bool,
    amount_yuan: str | None,
    original_currency: str,
    merchant: str | None,
    category: str,
    note: str,
    tags: str,
    expense_time: str | None,
) -> WebExpenseConfirmOutcome:
    """Confirm the snapshot, atomically persisting submitted edits when requested."""

    form_values: dict[str, str] | None = None
    field_errors: dict[str, str] | None = None
    update_payload = None
    if save_before_confirm:
        update_payload, prepared = prepare_web_expense_form(
            db,
            expense_id=expense_id,
            selected_ledger_id=selected_ledger_id,
            expected_row_version=expected_row_version,
            idempotency_key=idempotency_key,
            amount_yuan=amount_yuan,
            original_currency=original_currency,
            merchant=merchant,
            category=category,
            note=note,
            tags=tags,
            expense_time=expense_time,
        )
        if update_payload is None:
            return WebExpenseConfirmOutcome(
                error=prepared.error or "提交参数不正确，请检查后重试。",
                error_status=prepared.error_status,
                form_values=prepared.form_values,
                field_errors=prepared.field_errors,
            )
        parsed = update_payload.expected_row_version
        form_values = prepared.form_values
        field_errors = prepared.field_errors
    else:
        parsed = parse_form_row_version_token(expected_row_version)
        if parsed is None:
            return WebExpenseConfirmOutcome(error="页面已过期，请刷新后重新确认。")
    try:
        confirm_expense_submission(
            db,
            expense_id=expense_id,
            tenant_id=selected_ledger_id,
            expected_row_version=parsed,
            request_expected_row_version=parsed,
            idempotency_key=idempotency_key or None,
            intent_body=_confirmation_intent_body(form_values),
            update_payload=update_payload,
        )
    except AppError as exc:
        message = (
            "账单已在其它端被修改，请刷新后重新确认。"
            if exc.error == "state_conflict"
            else exc.message
        )
        if form_values and exc.error in _ROTATE_IDEMPOTENCY_ERRORS:
            form_values = {**form_values, "idempotency_key": ""}
        return WebExpenseConfirmOutcome(
            error=message,
            error_status=web_form_error_status(exc),
            form_values=form_values,
            field_errors=field_errors,
            conflict=exc.error == "state_conflict",
        )
    return WebExpenseConfirmOutcome()


def _confirmation_intent_body(
    form_values: dict[str, str] | None,
) -> dict[str, object]:
    if form_values is None:
        return {}
    metadata = {"expected_row_version", "idempotency_key"}
    return {
        "save_before_confirm": True,
        **{key: value for key, value in form_values.items() if key not in metadata},
    }


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
            return_to=return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
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
            resolve_return_to(return_to, "/web/confirmed"),
            selected_id,
            msg=exc.message,
            flash_type="error",
            **return_context_params(
                return_to,
                return_month=return_month,
                return_filter=return_filter,
                return_page=return_page,
                return_tag=return_tag,
                return_query=return_query,
            ),
        )
    # ?fragment=1 returns the drawer fragment fetched by desktop.js.
    if fragment:
        return templates.TemplateResponse(
            request=request, name="_edit_drawer.html", context=ctx
        )
    # A8: full edit page only — wire the "找家人分摊" 发起卡 to the existing
    # /web/expenses/{id}/split-invite route (None hides the whole block).
    ctx["split_invite"] = build_split_invite_context(
        db,
        request,
        selected_ledger_id=selected_id,
        expense=ctx["expense"],
        can_write=ctx["can_write"],
    )
    return templates.TemplateResponse(request=request, name="edit.html", context=ctx)


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    amount_yuan: str | None = Form(default=None),
    original_currency: str = Form(default=""),
    merchant: str | None = Form(default=None),
    category: str = Form(default=""),
    note: str = Form(default=""),
    # ``expense_time``: blank = leave untouched (FastAPI normalises a blank
    # optional Form to None, which matches the wanted semantics here).
    expense_time: str | None = Form(default=None),
    # Blank tags clear because the browser edit form always carries this field.
    tags: str = Form(default=""),
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    # 批10 review flow: ``return_to`` (whitelist, no-JS path) sends a successful
    # save back to a list page instead of /web/expenses/{id}/edit — fixing the
    # "saved → popped out of the queue" full-page bounce even with JS off.
    # ``fragment`` switches the response to the drawer fetch-mutation contract:
    # success → tiny 200 marker, error → the drawer fragment carrying the error.
    return_to: str = Form(default=""),
    return_month: str = Form(default=""),
    return_filter: str = Form(default=""),
    return_page: str = Form(default=""),
    return_tag: str = Form(default=""),
    return_query: str = Form(default=""),
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    outcome = apply_web_expense_form(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
        amount_yuan=amount_yuan,
        original_currency=original_currency,
        merchant=merchant,
        category=category,
        note=note,
        tags=tags,
        expense_time=expense_time,
        update_command=update_expense,
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
        fragment=fragment,
        return_to=return_to,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
    )


@router.post("/expenses/{expense_id}/confirm", response_class=HTMLResponse)
def web_confirm(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    save_before_confirm: int = Form(default=0),
    amount_yuan: str | None = Form(default=None),
    original_currency: str = Form(default=""),
    merchant: str | None = Form(default=None),
    category: str = Form(default=""),
    note: str = Form(default=""),
    tags: str = Form(default=""),
    expense_time: str | None = Form(default=None),
    return_to: str = Form(default=""),
    return_month: str = Form(default=""),
    return_filter: str = Form(default=""),
    return_page: str = Form(default=""),
    return_tag: str = Form(default=""),
    return_query: str = Form(default=""),
    # 批10: ``fragment=1`` switches confirm to the drawer fetch-mutation contract
    # (success → tiny 200 so the client removes the row + opens the next drawer;
    # error → the drawer fragment carrying the error).
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    outcome = confirm_web_expense(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
        save_before_confirm=save_before_confirm == 1,
        amount_yuan=amount_yuan,
        original_currency=original_currency,
        merchant=merchant,
        category=category,
        note=note,
        tags=tags,
        expense_time=expense_time,
    )
    if outcome.error is not None:
        return confirm_reject_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            outcome.error,
            fragment,
            status_code=outcome.error_status,
            return_to=return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
            form_values=outcome.form_values,
            field_errors=outcome.field_errors,
            conflict=outcome.conflict,
        )
    if fragment:
        return drawer_fragment_ok("confirm")
    success_return_to = return_to or "pending"
    return _web_redirect(
        resolve_return_to(return_to, "/web/pending"),
        selected_id,
        **return_context_params(
            success_return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        ),
    )


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    return_to: str = Form(default=""),
    return_month: str = Form(default=""),
    return_filter: str = Form(default=""),
    return_page: str = Form(default=""),
    return_tag: str = Form(default=""),
    return_query: str = Form(default=""),
    # 批10: ``fragment=1`` switches reject to the drawer fetch-mutation contract.
    # The full-page (no-JS) success keeps the ADR-0038 5s 撤销 banner via the
    # /web/pending redirect; the in-drawer fast path just removes the row (the
    # row stays server-side restorable for 5 min regardless — see soft_delete).
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return confirm_reject_error(
            db, request, options, selected_id, expense_id,
            "页面已过期，请刷新后重新操作。", fragment,
            status_code=422,
            return_to=return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        )
    try:
        reject_expense(db, expense_id, selected_id, expected_row_version=parsed)
    except AppError as exc:
        db.rollback()
        error_msg = "账单已在其它端被修改，请刷新后重新操作。" if exc.error == "state_conflict" else exc.message
        return confirm_reject_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            error_msg,
            fragment,
            status_code=web_form_error_status(exc),
            return_to=return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        )
    if fragment:
        return drawer_fragment_ok("reject")
    # ADR-0038 undo: redirect to /web/pending with msg + just-rejected expense_id so
    # the page renders a 5s 撤销 banner. The row stays restorable until the 5-min
    # retention cutoff in soft_delete_policy (server-side; the banner auto-dismisses
    # at 5s on the client). /web/pending reads ``undo`` from the query string.
    return _web_redirect(
        "/web/pending",
        selected_id,
        msg="已忽略这笔账单。",
        undo=str(expense_id),
        flash_type="success",
        **return_context_params("pending", return_filter=return_filter),
    )


@router.post("/expenses/{expense_id}/undo", response_class=HTMLResponse)
def web_expense_undo(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # ADR-0038 undo: restore a recently-rejected expense from the 5s banner.
    # PR-A added the ``expected_row_version`` token — without it, a stale /undo
    # POST from a cached banner could un-do a NEW intentional reject if the
    # user re-rejected the same row in between. /web/pending seeds the form's
    # hidden field with the row's updated_at at banner-render time; this route
    # parses it and lets ``undo_reject_expense``'s atomic UPDATE WHERE either
    # match (token still current → restore) or rowcount=0 (token stale →
    # 404 → flash "无法撤销"). Past-window / wrong-status / cross-tenant /
    # missing-row / stale-token all collapse to one flash message + flash_type=error.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/pending", selected_id,
            msg="页面已过期，请刷新后重新操作。", flash_type="error",
        )
    try:
        undo_reject_expense(db, expense_id, selected_id, parsed)
        msg = "已撤销，账单已恢复待确认。"
        flash_type = "success"
    except AppError:
        # ``undo_reject_expense`` only raises ``expense_not_found`` today (covers
        # past-window / wrong-status / cross-tenant / missing-row / stale-token
        # uniformly). One bucket covers all from the user's POV.
        msg = "无法撤销：账单已超过 5 分钟保留窗口，或已被清理。"
        flash_type = "error"
    return _web_redirect("/web/pending", selected_id, msg=msg, flash_type=flash_type)
