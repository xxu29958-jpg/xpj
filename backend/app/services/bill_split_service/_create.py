"""Sender creates an invitation against an expense they own."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, BillSplitInvitation, Expense
from app.money_contract import MoneySign, ensure_money_minor, fold_sum_to_int
from app.services.bill_split_service._common import (
    INVITATION_TTL,
    SPLIT_RECEIVED_SOURCE,
    _audit,
    _display_name,
    _load_writer_member,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import normalize_currency_code
from app.services.time_service import now_utc

_PENDING_DUPLICATE_INDEX = "uq_bill_split_invitations_pending_receiver"
_UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_pending_duplicate_error(exc: IntegrityError) -> bool:
    """Match only the PostgreSQL partial-UNIQUE guard for pending invites."""

    orig = exc.orig
    diagnostic = getattr(orig, "diag", None)
    return (
        getattr(orig, "sqlstate", None) == _UNIQUE_VIOLATION_SQLSTATE
        and getattr(diagnostic, "constraint_name", None) == _PENDING_DUPLICATE_INDEX
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
    _validate_invitation_request(
        sender_account_id=sender_account_id,
        receiver_account_id=receiver_account_id,
        amount_cents=amount_cents,
    )
    resolve_write_capability(db)
    sender_member = _load_writer_member(db, sender_ledger_id, sender_account_id)
    expense = _load_split_parent_expense(db, sender_ledger_id=sender_ledger_id, expense_id=expense_id)
    _ensure_parent_can_be_split(expense, amount_cents=amount_cents)
    sender, receiver = _load_invitation_parties(
        db,
        sender_account_id=sender_account_id,
        receiver_account_id=receiver_account_id,
    )
    _ensure_invitation_capacity(
        db,
        expense=expense,
        receiver_account_id=receiver_account_id,
        amount_cents=amount_cents,
    )
    invitation = _build_invitation(
        sender_account_id=sender_account_id,
        sender_ledger_id=sender_ledger_id,
        sender_member_id=sender_member.id,
        expense=expense,
        sender=sender,
        receiver=receiver,
        receiver_account_id=receiver_account_id,
        amount_cents=amount_cents,
    )
    db.add(invitation)
    # Flush before audit so invitation.public_id is available.
    _flush_invitation_or_raise(db)
    _audit(
        db,
        sender_ledger_id,
        "bill_split_invited",
        actor_account_id=sender_account_id,
        target_account_id=receiver_account_id,
        invitation_public_id=invitation.public_id,
    )
    db.commit()
    db.refresh(invitation)
    return invitation


def _validate_invitation_request(*, sender_account_id: int, receiver_account_id: int, amount_cents: int) -> None:
    ensure_money_minor(
        amount_cents,
        sign=MoneySign.POSITIVE,
        label="bill_split.amount_cents",
        error_code="split_amount_invalid",
        error_message="请填写有效范围内的拆账金额。",
    )
    if receiver_account_id == sender_account_id:
        raise AppError("split_receiver_invalid", status_code=422)


def _load_split_parent_expense(db: Session, *, sender_ledger_id: str, expense_id: int) -> Expense:
    # Row-lock the parent so active-split total + cap check + insert serialize
    # against concurrent invites on the same parent (PG locks, SQLite ignores).
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id).where(Expense.tenant_id == sender_ledger_id).with_for_update()
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense


def _ensure_parent_can_be_split(expense: Expense, *, amount_cents: int) -> None:
    if expense.source == SPLIT_RECEIVED_SOURCE:
        raise AppError(
            "split_chain_not_allowed",
            "不能对收到的拆账邀请再次拆账。",
            status_code=400,
        )
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


def _load_invitation_parties(
    db: Session, *, sender_account_id: int, receiver_account_id: int
) -> tuple[Account, Account]:
    receiver = db.get(Account, receiver_account_id)
    if receiver is None:
        raise AppError("split_receiver_invalid", status_code=422)
    sender = db.get(Account, sender_account_id)
    assert sender is not None  # AuthContext already validated this
    return sender, receiver


def _ensure_invitation_capacity(
    db: Session,
    *,
    expense: Expense,
    receiver_account_id: int,
    amount_cents: int,
) -> None:
    assert expense.amount_cents is not None
    active_split_total = fold_sum_to_int(
        db.scalar(
            select(func.coalesce(func.sum(BillSplitInvitation.amount_cents), 0))
            .where(BillSplitInvitation.sender_expense_id == expense.id)
            .where(BillSplitInvitation.status.in_(("invited", "accepted")))
        ),
        label="bill_split.active_split_total",
    )
    requested_total = fold_sum_to_int(
        active_split_total + amount_cents,
        label="bill_split.requested_total",
    )
    if requested_total > expense.amount_cents:
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


def _build_invitation(
    *,
    sender_account_id: int,
    sender_ledger_id: str,
    sender_member_id: int,
    expense: Expense,
    sender: Account,
    receiver: Account,
    receiver_account_id: int,
    amount_cents: int,
) -> BillSplitInvitation:
    now = now_utc()
    home_currency = normalize_currency_code(expense.home_currency_code)
    original_currency = normalize_currency_code(expense.original_currency_code)
    return BillSplitInvitation(
        sender_account_id=sender_account_id,
        sender_ledger_id=sender_ledger_id,
        sender_member_id=sender_member_id,
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


def _flush_invitation_or_raise(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _is_pending_duplicate_error(exc):
            raise AppError("split_invitation_already_pending", status_code=409) from exc
        raise


def _exchange_rate_datetime(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.combine(value, time.min, tzinfo=UTC)
