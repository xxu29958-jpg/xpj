"""/web expense edit / save / confirm / reject — expense 主体 routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import (
    _edit_page_or_flash_redirect,
    drawer_fragment_error,
    drawer_fragment_ok,
    parse_expense_time_local,
    parse_original_amount,
    resolve_return_to,
    web_edit_context,
)
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import (
    confirm_expense,
    reject_expense,
    undo_reject_expense,
    update_expense,
)

router = APIRouter(prefix="/web", tags=["web"])


def _confirm_reject_error(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    error_msg: str,
    fragment: int,
) -> Response:
    """批10: pick the confirm/reject error response by request mode.

    A drawer fetch-mutation (``fragment=1``) gets the drawer fragment swapped
    back in-place (or the empty-cell snippet when the row vanished); the no-JS
    full-page POST keeps the existing edit-page-or-flash-redirect behaviour
    (fallback list = /web/pending for both confirm and reject).
    """
    if fragment:
        return drawer_fragment_error(
            db, request, options, selected_id, expense_id, error_msg
        )
    return _edit_page_or_flash_redirect(
        db, request, options, selected_id, expense_id, error_msg, "/web/pending"
    )


def _web_save_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    error: str | None,
    fragment: int,
    return_to: str,
) -> Response:
    """批10: build the save response by request mode (kept out of ``web_save`` so
    that handler stays thin AND visibly delegates to ``update_expense``).

    Error: a drawer fetch swaps the fragment back in-place; the no-JS POST
    re-renders the edit page or flash-redirects (fallback /web/confirmed when the
    row is gone). Success: a fetch gets the tiny 200 marker; the no-JS POST
    honours the whitelisted ``return_to`` (so a drawer save lands back on the
    queue) and otherwise defaults to the full edit page for the direct link.
    """
    if error is not None:
        if fragment:
            return drawer_fragment_error(
                db, request, options, selected_id, expense_id, error
            )
        return _edit_page_or_flash_redirect(
            db, request, options, selected_id, expense_id, error, "/web/confirmed"
        )
    if fragment:
        return drawer_fragment_ok("save")
    return _web_redirect(
        resolve_return_to(return_to, f"/web/expenses/{expense_id}/edit"), selected_id
    )


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    fragment: int = 0,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    try:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
    except AppError as exc:
        # A deleted / cross-ledger expense (stale link, switched ledger) must
        # not surface as a bare-JSON page — or, for the drawer fetch, as raw
        # JSON injected into the drawer (desktop.js does not check res.ok).
        if fragment:
            return HTMLResponse(
                f'<div class="empty-cell">{exc.message}</div>',
                status_code=exc.status_code,
            )
        return _web_redirect("/web/confirmed", selected_id, msg=exc.message)
    # ?fragment=1 returns the drawer fragment fetched by desktop.js.
    template_name = "_edit_drawer.html" if fragment else "edit.html"
    return templates.TemplateResponse(request=request, name=template_name, context=ctx)


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    amount_yuan: str = Form(default=""),
    original_currency: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    note: str = Form(default=""),
    # ``expense_time``: blank = leave untouched (FastAPI normalises a blank
    # optional Form to None, which matches the wanted semantics here).
    expense_time: str | None = Form(default=None),
    # ``tags``: blank = CLEAR. FastAPI normalises a blank ``str | None`` Form
    # to None, making blank indistinguishable from omitted — so this field is
    # a non-optional str and is forwarded unconditionally. The /web edit form
    # always renders the input, so every browser submit carries it; the API
    # PATCH (JSON, exclude_unset) keeps the richer omitted-leaves semantics.
    tags: str = Form(default=""),
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    # 批10 review flow: ``return_to`` (whitelist, no-JS path) sends a successful
    # save back to a list page instead of /web/expenses/{id}/edit — fixing the
    # "saved → popped out of the queue" full-page bounce even with JS off.
    # ``fragment`` switches the response to the drawer fetch-mutation contract:
    # success → tiny 200 marker, error → the drawer fragment carrying the error.
    return_to: str = Form(default=""),
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    original_amount, error = parse_original_amount(amount_yuan)
    expense_time_value, time_error = parse_expense_time_local(expense_time)
    if error is None:
        error = time_error

    if error is None:
        # ADR-0038: the hidden ``expected_row_version`` is forwarded as the OCC
        # token; ``update_expense``'s atomic claim returns 409 ``state_conflict``
        # for a stale form. Blank time stays unset (= leave); ``tags`` always
        # forwards so "" clears (normalize_tags("") -> None), matching the /web
        # form which always renders the field.
        payload_args: dict[str, object] = {
            "expected_row_version": expected_row_version,
            "merchant": merchant.strip() or None,
            "category": category.strip() or None,
            "note": note.strip() or None,
            "tags": tags,
        }
        if expense_time_value is not None:
            payload_args["expense_time"] = expense_time_value
        if original_amount is not None:
            payload_args["original_currency"] = (original_currency or "").strip().upper() or None
            payload_args["original_amount"] = original_amount
        try:
            update_expense(db, expense_id, selected_id, ExpenseUpdateRequest(**payload_args))
        except ValueError as exc:
            error = f"提交参数不正确：{exc}"
        except AppError as exc:
            error = exc.message

    return _web_save_response(
        db, request, options, selected_id, expense_id,
        error=error, fragment=fragment, return_to=return_to,
    )


@router.post("/expenses/{expense_id}/confirm", response_class=HTMLResponse)
def web_confirm(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    # 批10: ``fragment=1`` switches confirm to the drawer fetch-mutation contract
    # (success → tiny 200 so the client removes the row + opens the next drawer;
    # error → the drawer fragment carrying the error). No ``return_to``: confirm's
    # full-page success already lands on /web/pending.
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _confirm_reject_error(
            db, request, options, selected_id, expense_id,
            "页面已过期，请刷新后重新确认。", fragment,
        )
    try:
        confirm_expense(db, expense_id, selected_id, expected_row_version=parsed)
    except AppError as exc:
        # ADR-0038 PR-2b: 409 state_conflict surfaces a clearer message
        # than the generic AppError text because user has to refetch.
        error_msg = "账单已在其它端被修改，请刷新后重新确认。" if exc.error == "state_conflict" else exc.message
        return _confirm_reject_error(
            db, request, options, selected_id, expense_id, error_msg, fragment
        )
    if fragment:
        return drawer_fragment_ok("confirm")
    return _web_redirect("/web/pending", selected_id)


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
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
        return _confirm_reject_error(
            db, request, options, selected_id, expense_id,
            "页面已过期，请刷新后重新操作。", fragment,
        )
    try:
        reject_expense(db, expense_id, selected_id, expected_row_version=parsed)
    except AppError as exc:
        error_msg = "账单已在其它端被修改，请刷新后重新操作。" if exc.error == "state_conflict" else exc.message
        return _confirm_reject_error(
            db, request, options, selected_id, expense_id, error_msg, fragment
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
