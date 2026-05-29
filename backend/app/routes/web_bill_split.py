"""ADR-0029 cross-ledger bill split — /web UI surface.

Three pages + four POST handlers:

- ``GET /web/bill-splits/inbox`` — receiver view (account-scoped)
- ``GET /web/bill-splits/sent`` — sender view (ledger-scoped)
- ``POST /web/expenses/{id}/split-invite`` — sender creates an invitation
  from an expense detail page
- ``POST /web/bill-splits/{public_id}/accept`` — receiver picks
  ``target_ledger_id`` and accepts
- ``POST /web/bill-splits/{public_id}/reject`` — receiver declines
- ``POST /web/bill-splits/{public_id}/cancel`` — sender retracts a still-
  invited invitation

Account resolution: when public-host session is present, the resolver
uses session.account_id; in loopback mode (owner console) it falls
back to the owner Account of the currently-selected ledger.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.services import bill_split_service as bsplit
from app.services.ledger_service import (
    find_owner_account_id_for_ledger,
    list_writer_ledger_ids_for_account,
)
from app.services.time_service import ensure_utc, now_utc

router = APIRouter(prefix="/web", tags=["web"])


# -------------------------------------------------------------------------
# Account resolver


def _resolve_request_account_id(
    db: Session, request: Request, *, selected_ledger_id: str
) -> int:
    """Pick the account the current /web request acts as."""
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.account_id
    # Loopback owner console: use the owner of the selected ledger.
    account_id = find_owner_account_id_for_ledger(
        db, ledger_id=selected_ledger_id
    )
    if account_id is None:
        raise AppError(
            "bill_split_owner_account_missing",
            "未找到 owner 账号；请检查 LedgerMember 配置。",
            status_code=400,
        )
    return account_id


# -------------------------------------------------------------------------
# Inbox + Sent pages


@router.get("/bill-splits/inbox", response_class=HTMLResponse)
def web_bill_split_inbox(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _resolve_request_account_id(db, request, selected_ledger_id=selected_id)

    invitations = bsplit.list_inbox(db, receiver_account_id=account_id, status="invited")

    # Single query pulls every writer ledger the receiver belongs to; per
    # invited row we just in-memory exclude the sender's ledger (same-ledger
    # accept is blocked at the service layer too). No N+1 over invitations.
    writer_ledger_ids = list_writer_ledger_ids_for_account(
        db, account_id=account_id
    )
    rows = []
    for inv in invitations:
        choices: list[dict] = []
        if inv.status == "invited":
            for ledger_id_choice in writer_ledger_ids:
                if ledger_id_choice == inv.sender_ledger_id:
                    continue
                choices.append({"ledger_id": ledger_id_choice})
        rows.append({
            "public_id": inv.public_id,
            "status": inv.status,
            "amount_yuan": _cents_to_yuan(inv.amount_cents),
            "sender_display_name": inv.sender_display_name,
            "merchant": inv.merchant_snapshot or "",
            "category": inv.category_suggestion or "",
            "expense_time": inv.expense_time_snapshot,
            "expires_at": inv.expires_at,
            "is_expired": ensure_utc(inv.expires_at) <= now_utc() if inv.status == "invited" else False,
            "accept_choices": choices,
        })

    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="拆账收件箱",
    )
    ctx["bill_split_rows"] = rows
    ctx["message"] = msg
    return templates.TemplateResponse(
        request=request, name="bill_splits_inbox.html", context=ctx
    )


@router.get("/bill-splits/sent", response_class=HTMLResponse)
def web_bill_split_sent(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _resolve_request_account_id(db, request, selected_ledger_id=selected_id)

    invitations = bsplit.list_sent(
        db, sender_account_id=account_id, sender_ledger_id=selected_id
    )
    rows = [
        {
            "public_id": inv.public_id,
            "status": inv.status,
            "amount_yuan": _cents_to_yuan(inv.amount_cents),
            "receiver_display_name": inv.receiver_display_name_snapshot or "",
            "merchant": inv.merchant_snapshot or "",
            "expense_time": inv.expense_time_snapshot,
            "expires_at": inv.expires_at,
        }
        for inv in invitations
    ]

    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="已发出拆账",
    )
    ctx["bill_split_rows"] = rows
    ctx["message"] = msg
    return templates.TemplateResponse(
        request=request, name="bill_splits_sent.html", context=ctx
    )


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
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    sender_account_id = _resolve_request_account_id(
        db, request, selected_ledger_id=selected_id
    )

    amount_cents = _yuan_to_cents(amount_yuan)
    if amount_cents is None or amount_cents <= 0:
        raise AppError("split_amount_invalid", "拆账金额不正确。", status_code=422)

    # The lookups above are read-only. End that read transaction so the service
    # can take its own SQLite writer guard before checking active split totals.
    db.rollback()
    bsplit.create_invitation(
        db,
        sender_account_id=sender_account_id,
        sender_ledger_id=selected_id,
        expense_id=expense_id,
        receiver_account_id=receiver_account_id,
        amount_cents=amount_cents,
    )
    return _web_redirect("/web/bill-splits/sent", selected_id, msg="已发起拆账邀请。")


@router.post(
    "/bill-splits/{public_id}/accept",
    response_class=HTMLResponse,
)
def web_split_accept(
    public_id: str,
    request: Request,
    target_ledger_id: str = Form(),
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    account_id = _resolve_request_account_id(db, request, selected_ledger_id=selected_id)
    bsplit.accept_invitation(
        db,
        public_id=public_id,
        accepting_account_id=account_id,
        target_ledger_id=target_ledger_id,
    )
    return _web_redirect("/web/bill-splits/inbox", selected_id, msg="已接受拆账邀请。")


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
    account_id = _resolve_request_account_id(db, request, selected_ledger_id=selected_id)
    bsplit.reject_invitation(db, public_id=public_id, rejecting_account_id=account_id)
    return _web_redirect("/web/bill-splits/inbox", selected_id, msg="已拒绝拆账邀请。")


@router.post(
    "/bill-splits/{public_id}/cancel",
    response_class=HTMLResponse,
)
def web_split_cancel(
    public_id: str,
    request: Request,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    account_id = _resolve_request_account_id(db, request, selected_ledger_id=selected_id)
    bsplit.cancel_invitation(db, public_id=public_id, sender_account_id=account_id)
    return _web_redirect("/web/bill-splits/sent", selected_id, msg="已撤回拆账邀请。")


# -------------------------------------------------------------------------
# Money helpers (kept local to avoid expense-module coupling)


def _cents_to_yuan(cents: int | None) -> str:
    if cents is None:
        return "0.00"
    return f"{cents / 100:.2f}"


def _yuan_to_cents(value: str) -> int | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return int((Decimal(cleaned) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None
