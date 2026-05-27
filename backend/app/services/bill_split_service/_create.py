"""Sender creates an invitation against an expense they own."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, BillSplitInvitation, Expense
from app.services.bill_split_service._common import (
    INVITATION_TTL,
    SPLIT_RECEIVED_SOURCE,
    _audit,
    _display_name,
    _load_writer_member,
)
from app.services.time_service import now_utc

_PENDING_DUPLICATE_INDEX = "uq_bill_split_invitations_pending_receiver"
_PENDING_DUPLICATE_COLUMNS = (
    "bill_split_invitations.sender_expense_id",
    "bill_split_invitations.receiver_account_id",
)


def _is_pending_duplicate_error(exc: IntegrityError) -> bool:
    message = str(exc.orig if exc.orig is not None else exc)
    return (
        _PENDING_DUPLICATE_INDEX in message
        or all(column in message for column in _PENDING_DUPLICATE_COLUMNS)
    )


def create_invitation(
    db: Session,
    *,
    sender_account_id: int,
    sender_ledger_id: str,
    expense_id: int,
    receiver_account_id: int,
    amount_cents: int,
) -> BillSplitInvitation:
    """Sender creates an invitation against an expense they own.

    Sender does NOT specify receiver_ledger_id — receiver picks at accept.
    """
    if amount_cents <= 0:
        raise AppError("invalid_request", "拆账金额必须大于 0。", status_code=422)

    if receiver_account_id == sender_account_id:
        raise AppError("invalid_request", status_code=422)

    # 1. Sender's role on sender_ledger must be writer.
    sender_member = _load_writer_member(db, sender_ledger_id, sender_account_id)

    # 2. Expense must belong to sender's ledger.
    expense = db.scalar(
        select(Expense)
        .where(Expense.id == expense_id)
        .where(Expense.tenant_id == sender_ledger_id)
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)

    # 3. No chain split.
    if expense.source == SPLIT_RECEIVED_SOURCE:
        raise AppError(
            "split_chain_not_allowed",
            "不能对收到的拆账邀请再次拆账。",
            status_code=400,
        )

    # 4. Amount must not exceed parent expense.
    if expense.amount_cents is None:
        raise AppError(
            "invalid_request",
            "原账单金额未确定，无法发起拆账。",
            status_code=422,
        )
    if amount_cents > expense.amount_cents:
        raise AppError(
            "invalid_request",
            "拆账金额不能超过原账单金额。",
            status_code=422,
        )

    # 5. Receiver account must exist; build display snapshots.
    receiver = db.get(Account, receiver_account_id)
    if receiver is None:
        raise AppError("account_not_found", status_code=404)
    sender = db.get(Account, sender_account_id)
    assert sender is not None  # AuthContext already validated this

    pending_duplicate = db.scalar(
        select(BillSplitInvitation.id)
        .where(BillSplitInvitation.sender_expense_id == expense.id)
        .where(BillSplitInvitation.receiver_account_id == receiver_account_id)
        .where(BillSplitInvitation.status == "invited")
        .limit(1)
    )
    if pending_duplicate is not None:
        raise AppError("split_invitation_already_pending", status_code=409)

    now = now_utc()
    invitation = BillSplitInvitation(
        sender_account_id=sender_account_id,
        sender_ledger_id=sender_ledger_id,
        sender_member_id=sender_member.id,
        sender_expense_id=expense.id,
        sender_display_name=_display_name(sender),
        receiver_account_id=receiver_account_id,
        receiver_display_name_snapshot=_display_name(receiver),
        amount_cents=amount_cents,
        home_currency_code=expense.home_currency_code,
        original_currency_code=expense.original_currency_code,
        original_amount_minor=expense.original_amount_minor,
        exchange_rate_to_cny=expense.exchange_rate_to_cny,
        exchange_rate_date=None,  # date column copy is fragile; receiver snapshot uses dt
        exchange_rate_source=expense.exchange_rate_source,
        merchant_snapshot=expense.merchant,
        category_suggestion=expense.category,
        expense_time_snapshot=expense.expense_time,
        status="invited",
        expires_at=now + INVITATION_TTL,
        created_at=now,
    )
    db.add(invitation)
    try:
        db.flush()  # need invitation.public_id for audit row
    except IntegrityError as exc:
        db.rollback()
        if _is_pending_duplicate_error(exc):
            raise AppError("split_invitation_already_pending", status_code=409) from exc
        raise
    _audit(db, sender_ledger_id, "bill_split_invited",
           actor_account_id=sender_account_id,
           target_account_id=receiver_account_id,
           invitation_public_id=invitation.public_id)
    db.commit()
    db.refresh(invitation)
    return invitation
