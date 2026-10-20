"""Receiver and sender bill-split Web surfaces plus their form actions."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_bill_split_context import _cents_to_yuan, _fmt_local, inbox_rows, invitation_facts
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    require_draft_binding,
)
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    edit_context_params,
    expense_return_form_context,
    flow_href,
    resolve_return_to,
    return_context_params,
)
from app.routes._web_relationship_links import accepted_split_debt_links
from app.routes._web_session_common import (
    resolve_web_actor,
    resolve_web_actor_account_id,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.services import bill_split_service as bsplit
from app.services.currency_common import (
    currency_symbol,
    major_amount_to_minor,
    minor_amount_label,
)
from app.services.time_service import ensure_utc, now_utc

router = APIRouter(prefix="/web", tags=["web"])

_FLASH_TYPES = frozenset({"success", "error", "warning"})




def _accepted_receipt(
    db: Session,
    *,
    public_id: str | None,
    receiver_account_id: int,
    visible_ledger_names: dict[str, str],
) -> dict | None:
    """Hydrate a receiver-authorized receipt from the accepted invitation."""
    if not public_id:
        return None
    try:
        inv = bsplit.get_invitation(db, public_id)
    except AppError:
        return None
    received = bsplit.to_received_bill_reference(
        inv, receiver_account_id=receiver_account_id, visible_ledger_names=visible_ledger_names,
    )
    if received is None:
        return None
    debt_links = accepted_split_debt_links(
        db, [inv], selected_id=received["ledger_id"], account_id=receiver_account_id,
    )
    return {
        "amount_label": (
            f"{currency_symbol(inv.home_currency_code)}{_cents_to_yuan(inv.amount_cents, inv.home_currency_code)}"
        ),
        "ledger_name": received["ledger_name"],
        "debt_href": debt_links.get(inv.public_id, ""),
        "fact_href": flow_href(
            f"/web/expenses/{received['expense_id']}/edit",
            ledger_id=received["ledger_id"],
            return_to="bill_splits_inbox",
        ),
    }


def _clean_flash_type(value: str | None) -> str:
    return value if value in _FLASH_TYPES else ""


# -------------------------------------------------------------------------
# Inbox + Sent pages


@router.get("/bill-splits/inbox", response_class=HTMLResponse)
def web_bill_split_inbox(
    request: Request,
    ledger_id: str | None = None,
    status: Literal["invited", "all"] = "invited",
    msg: str | None = None,
    flash_type: str = "",
    accepted: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = resolve_web_actor_account_id(db, request, selected_id)

    invitations = bsplit.list_inbox(db, receiver_account_id=account_id, status=None if status == "all" else "invited")

    rows, ledger_names = inbox_rows(db, account_id, invitations, status=status)

    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="拆账收件箱",
    )
    ctx["bill_split_rows"] = rows
    ctx["splitaccept_draft_scope"] = browser_draft_scope(db, request)
    ctx["split_inbox_status"] = status
    ctx["flash_message"] = msg or ""
    ctx["flash_type"] = _clean_flash_type(flash_type)
    ctx["receipt"] = _accepted_receipt(
        db,
        public_id=accepted,
        receiver_account_id=account_id,
        visible_ledger_names=ledger_names,
    )
    return templates.TemplateResponse(request=request, name="bill_splits_inbox.html", context=ctx)


@router.get("/bill-splits/sent", response_class=HTMLResponse)
def web_bill_split_sent(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    flash_type: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = resolve_web_actor_account_id(db, request, selected_id)

    invitations = bsplit.list_sent(db, sender_account_id=account_id, sender_ledger_id=selected_id)
    debt_links = accepted_split_debt_links(db, invitations, selected_id=selected_id, account_id=account_id)
    presented_at = now_utc()
    rows = []
    for inv in invitations:
        is_expired = inv.status == "invited" and ensure_utc(inv.expires_at) <= presented_at
        rows.append(
            {
                **invitation_facts(inv),
                "public_id": inv.public_id,
                "status": inv.status,
                "amount_yuan": _cents_to_yuan(inv.amount_cents, inv.home_currency_code),
                "receiver_display_name": inv.receiver_display_name_snapshot or "",
                "merchant": inv.merchant_snapshot or "",
                "expense_time": _fmt_local(inv.expense_time_snapshot),
                "expires_at": _fmt_local(inv.expires_at),
                "is_expired": is_expired,
                "is_cancellable": inv.status == "invited" and not is_expired,
                "debt_href": debt_links.get(inv.public_id, ""),
                "current_share_label": (
                    f"{inv.home_currency_code} "
                    f"{minor_amount_label(inv.current_agreed_share_amount_cents, inv.home_currency_code)}"
                ) if inv.current_agreed_share_amount_cents != inv.amount_cents else "",
                "source_href": flow_href(
                    f"/web/expenses/{inv.sender_expense_id}/edit",
                    ledger_id=selected_id,
                    return_to="bill_splits_sent",
                ),
            }
        )

    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="已发出拆账",
    )
    ctx["bill_split_rows"] = rows
    ctx["flash_message"] = msg or ""
    ctx["flash_type"] = _clean_flash_type(flash_type)
    return templates.TemplateResponse(request=request, name="bill_splits_sent.html", context=ctx)


# -------------------------------------------------------------------------
# Form actions


@router.post(
    "/expenses/{expense_id}/split-invite",
    response_class=HTMLResponse,
)
def web_split_invite(
    expense_id: int,
    request: Request,
    receiver_account_id: int = Form(),
    amount_yuan: str = Form(),
    idempotency_key: str = Form(default=""),
    expected_row_version: int = Form(default=0),
    ledger_id: str = Form(default=""),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    sender_account_id = resolve_web_actor_account_id(db, request, selected_id)

    # Form failures (bad amount / cap exceeded / duplicate pending invite …)
    # flash back onto the page instead of escaping to the global AppError
    # handler, which renders a bare-JSON page in the browser.
    try:
        # Read without reversing the command owner's key -> parent lock order.
        # The owner rechecks this currency together with OCC under its lock.
        currency = bsplit.split_parent_home_currency(db, sender_ledger_id=selected_id, expense_id=expense_id)
        amount_cents = _yuan_to_cents(amount_yuan, currency)
        if amount_cents is None or amount_cents <= 0:
            raise AppError("split_amount_invalid", "拆账金额不正确。", status_code=422)
        bsplit.create_invitation(
            db,
            sender_account_id=sender_account_id,
            sender_ledger_id=selected_id,
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=amount_cents,
            idempotency_key=idempotency_key,
            expected_row_version=expected_row_version,
            expected_home_currency_code=currency,
        )
        msg = "已发起拆账邀请。"
        flash_type = "success"
    except AppError as exc:
        return _invite_error_response(db, request, options, selected_id, expense_id, exc,
            return_context=return_context,
            draft={"receiver_account_id": receiver_account_id, "amount_yuan": amount_yuan,
                   "idempotency_key": idempotency_key, "expected_row_version": expected_row_version})
    return _web_redirect(
        "/web/bill-splits/sent",
        selected_id,
        msg=msg,
        flash_type=flash_type,
    )


def _invite_error_response(
    db, request, options, selected_id, expense_id, exc, *, draft, return_context: ExpenseReturnContext,
):
    from app.routes._web_expense_fact import web_fact_context

    db.rollback()
    try:
        ctx = web_fact_context(db, request, options, selected_id, expense_id,
            error=exc.message, return_context=return_context)
    except AppError:
        return _web_redirect(resolve_return_to(return_context.return_to, "/web/bill-splits/sent"),
            selected_id, msg=exc.message, flash_type="error", **return_context_params(**return_context.as_kwargs()))
    if ctx["split_invite"] is not None:
        ctx["split_invite"].update(draft, requires_review=exc.error in {
            "state_conflict", "idempotency_key_required", "idempotency_key_reused",
        })
    return templates.TemplateResponse(request=request, name="expense_fact.html", context=ctx,
        status_code=exc.status_code)


class SplitAcceptanceForm(BaseModel):
    ledger_id: str = ""
    target_ledger_id: str
    target_ledger_name: str = ""
    public_id: str = ""
    draft_scope: str = ""
    draft_ref: str = ""
    review_latest: bool = False
    csrf_token: str = ""


def _acceptance_page(request, db, *, options, selected_id, public_id, values=None, error=None, result="", original_only=False):
    account_id = resolve_web_actor_account_id(db, request, selected_id)
    invitation = bsplit.get_invitation(db, public_id)
    if invitation.receiver_account_id != account_id:
        raise AppError("invitation_not_yours", status_code=403)
    rows, _ = inbox_rows(db, account_id, [invitation], status="all")
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="接受拆账邀请")
    ctx.update(bill_split_rows=rows, split_inbox_status="all", accept_task=True,
        splitaccept_draft_scope=browser_draft_scope(db, request), accept_values=values or {},
        splitaccept_native_result=result, splitaccept_original_only=original_only,
        flash_message=error.message if error else "", flash_type="error" if error else "", receipt=None)
    return templates.TemplateResponse(request=request, name="bill_splits_inbox.html", context=ctx,
        status_code=error.status_code if error else 200, headers={"Cache-Control": "no-store"})


@router.get("/bill-splits/{public_id}/accept", response_class=HTMLResponse)
def web_split_acceptance_task(public_id: str, request: Request, ledger_id: str | None = None,
                              original_only: bool = False, _local: None = LocalOnly,
                              db: Session = Depends(get_db)) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _acceptance_page(request, db, options=options, selected_id=selected_id, public_id=public_id,
        original_only=original_only)


@router.post("/bill-splits/{public_id}/accept", response_class=HTMLResponse)
def web_split_accept(public_id: str, request: Request, form: Annotated[SplitAcceptanceForm, Form()],
                     _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    values = form.model_dump(exclude={"csrf_token", "review_latest"})
    try:
        if form.draft_scope or "application/json" in request.headers.get("accept", ""):
            require_draft_binding(db, request, ledger_id=selected_id, draft_scope=form.draft_scope, require_session=False,
                original_ledger_id=form.ledger_id)
        if retained := preserve_original_ledger_form(request, db, options=options, selected=selected_id,
                fields=values, task="接受原拆账邀请"):
            return retained
        account_id, device_id = resolve_web_actor(db, request, selected_id)
        if form.public_id and form.public_id != public_id:
            raise AppError("state_conflict", "原邀请已变化，请从保留的接受任务重新打开。", status_code=409)
        if form.review_latest:
            return _acceptance_page(request, db, options=options, selected_id=selected_id, public_id=public_id,
                values=values, result="prepared")
        invitation, _received = bsplit.accept_invitation(
            db, public_id=public_id, accepting_account_id=account_id,
            target_ledger_id=form.target_ledger_id, accepting_device_id=device_id)
    except AppError as exc:
        db.rollback()
        # These owner refusals are resolved after the accepted/same-target replay;
        # they prove this target did not acquire a second received expense.
        result = "rejected" if exc.error in {"ledger_forbidden", "ledger_archived", "invitation_expired",
            "invitation_not_acceptable", "state_conflict"} else "blocked"
        if response := draft_error_response(request, exc, refusal_result=result):
            return response
        if exc.error in {"session_binding_changed", "invalid_token", "invitation_not_yours", "invitation_not_found"}:
            return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
                fields=values, task="接受原拆账邀请", error=exc)
        return _acceptance_page(request, db, options=options, selected_id=selected_id, public_id=public_id,
            values=values, error=exc, result=result)
    destination = _web_redirect("/web/bill-splits/inbox", selected_id, accepted=invitation.public_id, flash_type="success")
    if response := draft_ack_response(request, draft_scope=form.draft_scope, idempotency_key=public_id,
            receipt={"public_id": public_id, "status": invitation.status, "target_ledger_id": form.target_ledger_id,
                "amount_cents": invitation.amount_cents, "home_currency_code": invitation.home_currency_code},
            next_href=destination.headers["location"]):
        return response
    return destination


@router.post(
    "/bill-splits/{public_id}/reject",
    response_class=HTMLResponse,
)
def web_split_reject(
    public_id: str,
    request: Request,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    account_id = resolve_web_actor_account_id(db, request, selected_id)
    try:
        bsplit.reject_invitation(db, public_id=public_id, rejecting_account_id=account_id)
        msg = "已拒绝拆账邀请。"
        flash_type = "success"
    except AppError as exc:
        msg = exc.message
        flash_type = "error"
    return _web_redirect(
        "/web/bill-splits/inbox",
        selected_id,
        msg=msg,
        flash_type=flash_type,
    )


@router.post(
    "/bill-splits/{public_id}/cancel",
    response_class=HTMLResponse,
)
def web_split_cancel(
    public_id: str,
    request: Request,
    ledger_id: str = Form(default=""),
    return_expense_id: int = Form(default=0),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    account_id = resolve_web_actor_account_id(db, request, selected_id)
    try:
        bsplit.cancel_invitation(db, public_id=public_id, sender_account_id=account_id)
        msg = "已撤回拆账邀请。"
        flash_type = "success"
    except AppError as exc:
        msg = exc.message
        flash_type = "error"
    # 编辑页发起卡的撤回带 return_expense_id 回编辑页(int 类型天然挡住任意
    # 跳转目标;0=未带,落已发列表——sent 页自己的撤回表单不带此字段)。
    target = f"/web/expenses/{return_expense_id}/edit" if return_expense_id > 0 else "/web/bill-splits/sent"
    origin = edit_context_params(**return_context.as_kwargs()) if return_expense_id > 0 else {}
    return _web_redirect(target, selected_id, msg=msg, flash_type=flash_type, **origin)


# -------------------------------------------------------------------------
# Money helpers (kept local to avoid expense-module coupling)




def _yuan_to_cents(value: str, currency_code: str) -> int | None:
    # The write form parses against the same persisted authority its resulting
    # invitation will freeze, never against mutable process configuration.
    raw = value or ""
    if not raw:
        return None
    try:
        return major_amount_to_minor(raw, currency_code)
    except AppError:
        return None
