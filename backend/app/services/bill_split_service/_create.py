"""Sender creates an invitation against an expense they own."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
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
from app.services.currency_common import normalize_currency_code
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
        raise AppError("split_amount_invalid", "拆账金额必须大于 0。", status_code=422)

    if receiver_account_id == sender_account_id:
        raise AppError("split_receiver_invalid", status_code=422)

    _begin_split_create_transaction(db)

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
            "split_parent_amount_missing",
            "原账单金额未确定，无法发起拆账。",
            status_code=422,
        )
    if amount_cents > expense.amount_cents:
        raise AppError(
            "split_amount_exceeds_parent",
            "拆账金额不能超过原账单金额。",
            status_code=422,
        )

    # 5. Receiver account must exist; build display snapshots. Keep the
    # public error generic so this endpoint cannot be used as an account
    # existence oracle.
    receiver = db.get(Account, receiver_account_id)
    if receiver is None:
        raise AppError("split_receiver_invalid", status_code=422)
    sender = db.get(Account, sender_account_id)
    assert sender is not None  # AuthContext already validated this

    active_split_total = int(
        db.scalar(
            select(func.coalesce(func.sum(BillSplitInvitation.amount_cents), 0))
            .where(BillSplitInvitation.sender_expense_id == expense.id)
            .where(BillSplitInvitation.status.in_(("invited", "accepted")))
        )
        or 0
    )
    if active_split_total + amount_cents > expense.amount_cents:
        raise AppError(
            "split_total_exceeds_parent",
            "拆账邀请总额不能超过原账单金额。",
            status_code=422,
        )

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
    home_currency = normalize_currency_code(expense.home_currency_code)
    original_currency = normalize_currency_code(expense.original_currency_code)
    invitation = BillSplitInvitation(
        sender_account_id=sender_account_id,
        sender_ledger_id=sender_ledger_id,
        sender_member_id=sender_member.id,
        sender_expense_id=expense.id,
        sender_display_name=_display_name(sender),
        receiver_account_id=receiver_account_id,
        receiver_display_name_snapshot=_display_name(receiver),
        amount_cents=amount_cents,
        home_currency_code=home_currency,
        original_currency_code=original_currency,
        original_amount_minor=expense.original_amount_minor,
        exchange_rate_to_cny=expense.exchange_rate_to_cny,
        exchange_rate_date=_exchange_rate_datetime(expense.exchange_rate_date),
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


def _begin_split_create_transaction(db: Session) -> None:
    """Serialize split-create checks that depend on parent active total.

    The business invariant is "active invitations for one parent expense must
    not exceed the parent amount". SQLite cannot express that as a CHECK across
    rows, so cloud / multi-worker deployments need the create path to take a
    writer transaction before reading active totals and inserting the invite.
    """

    if db.in_transaction():
        raise AppError(
            "state_conflict",
            "Cannot create a bill split invitation inside an active transaction.",
            status_code=409,
        )
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _exchange_rate_datetime(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.combine(value, time.min, tzinfo=UTC)
