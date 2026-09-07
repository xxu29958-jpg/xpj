"""Read-only split presentation shared by source facts and invitation lists."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.errors import AppError
from app.money_contract import projection_sum_to_int, projection_values_sum_to_int
from app.routes._web_session_common import resolve_web_actor_account_id
from app.services import bill_split_service as bsplit
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import minor_amount_value
from app.services.invitation_members import list_members
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import ensure_utc, now_utc

_INVITE_ACTIVE_STATUSES = ("invited", "accepted")


def _fmt_local(value) -> str:
    """Render a snapshot datetime in the accounting timezone."""
    if value is None:
        return ""
    return ensure_utc(value).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")


def _remaining_split_capacity(
    expense: dict,
    invitations: list,
    *,
    presentation_currency: str,
) -> tuple[str, int]:
    currency_code = expense.get("home_currency_code") or presentation_currency
    active_total = projection_values_sum_to_int(
        (invitation.amount_cents for invitation in invitations if invitation.status in _INVITE_ACTIVE_STATUSES),
        label="web_bill_split.active_total",
    )
    raw_parent = expense.get("amount_cents")
    parent = 0 if raw_parent is None else projection_sum_to_int(raw_parent, label="web_bill_split.parent_amount")
    remaining = projection_sum_to_int(
        parent - active_total,
        label="web_bill_split.remaining",
    )
    return currency_code, max(remaining, 0)


def build_split_invite_context(
    db: Session,
    request: Request,
    *,
    selected_ledger_id: str,
    expense: dict,
    can_write: bool,
) -> dict | None:
    """Context for the confirmed fact page's "找家人分摊" card, or ``None``.

    The card only makes sense for a **confirmed** expense that has an amount,
    is writable by the caller, and is not itself a received split (no chain
    split — ``create_invitation`` 也会兜底). When any of those fail, return
    ``None`` so the template skips the whole block (A8 wires the form to the
    pre-existing ``POST /web/expenses/{id}/split-invite`` route).

    The receiver dropdown lists the *current ledger's* other active members
    (拆账=发邀请到 TA 自己的账本，对照 Android 批 13 的概念区分；份额=记在本账本
    走编辑页下方的"家庭拆账"卡)。``account_id`` rides each option value as the
    ``receiver_account_id`` the route expects — an internal int, never shown.
    """
    if not (
        can_write
        and expense.get("status") == "confirmed"
        and expense.get("amount_cents") is not None
        and not expense.get("is_split_received")
    ):
        return None

    # Resolving the acting account can fail in loopback when no owner row
    # exists for the selected ledger; degrade to no-card rather than 500 the
    # whole edit page.
    try:
        sender_account_id = resolve_web_actor_account_id(db, request, selected_ledger_id)
    except AppError:
        return None

    members = [
        {
            "account_id": summary.account_id,
            "account_name": summary.account_name,
            "role": summary.role,
        }
        for summary in list_members(db, ledger_id=selected_ledger_id, requester_account_id=sender_account_id)
        if not summary.is_self and summary.disabled_at is None
    ]

    invitations = bsplit.list_sent_for_expense(db, sender_account_id=sender_account_id, expense_id=expense["id"])
    expense_currency, remaining_cents = _remaining_split_capacity(
        expense,
        invitations,
        presentation_currency=require_runtime_home_currency_code(db),
    )
    presented_at = now_utc()
    sent_rows = []
    for inv in invitations:
        is_expired = inv.status == "invited" and ensure_utc(inv.expires_at) <= presented_at
        sent_rows.append(
            {
                "public_id": inv.public_id,
                "status": "expired" if is_expired else inv.status,
                "amount_yuan": _cents_to_yuan(inv.amount_cents, inv.home_currency_code),
                "receiver_display_name": inv.receiver_display_name_snapshot or "",
                "expires_at": _fmt_local(inv.expires_at),
                "is_cancellable": inv.status == "invited" and not is_expired,
            }
        )

    return {
        "members": members,
        "idempotency_key": str(uuid4()),
        "expected_row_version": expense["row_version"],
        "sent_rows": sent_rows,
        "remaining_yuan": _cents_to_yuan(remaining_cents, expense_currency),
        "has_capacity": remaining_cents > 0,
    }


def _cents_to_yuan(cents: int | None, currency_code: str) -> str:
    # Frozen invitation/expense currency is presentation authority.
    if cents is None:
        cents = 0
    return minor_amount_value(cents, currency_code)
