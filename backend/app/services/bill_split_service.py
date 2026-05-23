"""ADR-0029 cross-ledger bill split workflow.

State machine + privacy boundaries. See the ADR for the full rationale;
key load-bearing points:

- **Account-scoped invitation**: sender chooses receiver_account_id; sender
  never knows which ledger receiver will pick.
- **Receiver picks ledger at accept**: ``target_ledger_id`` is supplied in
  the accept request body and the service checks the receiver has write
  role on that ledger.
- **Decoupled accepted expense**: a fresh ``Expense`` is created in the
  receiver's chosen ledger with ``source='bill_split_received'``; it does
  not FK back to sender's expense.
- **Idempotent accept**: ``received_expense_id`` is UNIQUE on the table,
  so re-accepting returns the already-created expense.
- **No chain split**: ``create_invitation`` refuses if the source expense
  itself was a received split.

Audit: LedgerAuditLog gains 5 action values (bill_split_invited /
accepted / rejected / cancelled / expired). The action column is already
a free-form String(64), so no schema change is needed there.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    BillSplitInvitation,
    Expense,
    LedgerAuditLog,
    LedgerMember,
)
from app.services.time_service import ensure_utc, now_utc

INVITATION_TTL = timedelta(days=30)
WRITER_ROLES = frozenset({"owner", "member"})
SPLIT_RECEIVED_SOURCE = "bill_split_received"


# -------------------------------------------------------------------------
# create_invitation


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
    db.flush()  # need invitation.public_id for audit row
    _audit(db, sender_ledger_id, "bill_split_invited",
           actor_account_id=sender_account_id,
           target_account_id=receiver_account_id,
           invitation_public_id=invitation.public_id)
    db.commit()
    db.refresh(invitation)
    return invitation


# -------------------------------------------------------------------------
# Queries


def list_sent(
    db: Session, *, sender_account_id: int, sender_ledger_id: str, limit: int = 50
) -> list[BillSplitInvitation]:
    """Sender view — ledger-scoped (sender_ledger_id is sender's current
    ledger, not invitation.receiver_ledger_id)."""
    rows = db.scalars(
        select(BillSplitInvitation)
        .where(BillSplitInvitation.sender_account_id == sender_account_id)
        .where(BillSplitInvitation.sender_ledger_id == sender_ledger_id)
        .order_by(BillSplitInvitation.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def list_inbox(
    db: Session, *, receiver_account_id: int, limit: int = 50
) -> list[BillSplitInvitation]:
    """Receiver view — **account-scoped, NOT ledger-scoped**. Receiver's
    inbox is the same no matter which ledger they're currently viewing,
    because invitations are not yet bound to a target ledger when they
    arrive."""
    rows = db.scalars(
        select(BillSplitInvitation)
        .where(BillSplitInvitation.receiver_account_id == receiver_account_id)
        .order_by(BillSplitInvitation.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def get_invitation(db: Session, public_id: str) -> BillSplitInvitation:
    inv = db.scalar(
        select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
    )
    if inv is None:
        raise AppError("invitation_not_found", status_code=404)
    return inv


# -------------------------------------------------------------------------
# accept


def accept_invitation(
    db: Session,
    *,
    public_id: str,
    accepting_account_id: int,
    target_ledger_id: str,
) -> tuple[BillSplitInvitation, Expense]:
    """Receiver accepts; service creates the decoupled Expense in the
    receiver's chosen ledger and binds the invitation."""
    inv = get_invitation(db, public_id)

    # Identity check first — don't leak any other state if caller isn't
    # the receiver.
    if accepting_account_id != inv.receiver_account_id:
        raise AppError("invitation_not_yours", status_code=403)

    # Idempotent: re-accepting returns the already-created expense.
    if inv.status == "accepted":
        if inv.received_expense_id is None or inv.receiver_ledger_id is None:
            # Should be impossible (UNIQUE constraint), but guard anyway.
            raise AppError("server_error", status_code=500)
        existing = db.scalar(
            select(Expense)
            .where(Expense.id == inv.received_expense_id)
            .where(Expense.tenant_id == inv.receiver_ledger_id)
        )
        if existing is None:
            raise AppError("server_error", status_code=500)
        return inv, existing
    if inv.status != "invited":
        raise AppError("invitation_not_acceptable", status_code=409)

    # Expiry check (do not silently auto-expire here — if exactly at TTL,
    # let the caller see a clear "expired" error then run the sweeper).
    # SQLite returns naive datetimes; coerce both sides to UTC-aware.
    if ensure_utc(inv.expires_at) <= now_utc():
        _mark_expired(db, inv)
        raise AppError("invitation_expired", status_code=410)

    # Target ledger constraints.
    if target_ledger_id == inv.sender_ledger_id:
        raise AppError(
            "ledger_forbidden",
            "不能接受到 sender 的同一个账本。",
            status_code=403,
        )
    target_member = _load_writer_member(db, target_ledger_id, accepting_account_id)

    # Build the receiver-side expense from the snapshot.
    now = now_utc()
    received = Expense(
        tenant_id=target_ledger_id,
        amount_cents=inv.amount_cents,
        home_currency_code=inv.home_currency_code,
        original_currency_code=inv.original_currency_code,
        original_amount_minor=inv.original_amount_minor,
        exchange_rate_to_cny=inv.exchange_rate_to_cny,
        exchange_rate_source=inv.exchange_rate_source,
        merchant=inv.merchant_snapshot,
        category=inv.category_suggestion or "其他",
        note=None,
        source=SPLIT_RECEIVED_SOURCE,
        status="confirmed",
        expense_time=inv.expense_time_snapshot,
        created_at=now,
        updated_at=now,
        confirmed_at=now,
        split_origin_invitation_id=inv.public_id,
    )
    db.add(received)
    try:
        db.flush()  # need received.id for invitation.received_expense_id
    except IntegrityError as exc:  # noqa: BLE001
        db.rollback()
        raise AppError("server_error", status_code=500) from exc

    inv.status = "accepted"
    inv.accepted_at = now
    inv.received_expense_id = received.id
    inv.receiver_ledger_id = target_ledger_id
    inv.receiver_member_id = target_member.id

    _audit(db, target_ledger_id, "bill_split_accepted",
           actor_account_id=accepting_account_id,
           target_account_id=inv.sender_account_id,
           invitation_public_id=inv.public_id)
    db.commit()
    db.refresh(inv)
    db.refresh(received)
    return inv, received


# -------------------------------------------------------------------------
# reject / cancel / expire


def reject_invitation(
    db: Session, *, public_id: str, rejecting_account_id: int
) -> BillSplitInvitation:
    inv = get_invitation(db, public_id)
    if rejecting_account_id != inv.receiver_account_id:
        raise AppError("invitation_not_yours", status_code=403)
    if inv.status != "invited":
        raise AppError("invitation_not_acceptable", status_code=409)
    inv.status = "rejected"
    inv.rejected_at = now_utc()
    _audit(db, inv.sender_ledger_id, "bill_split_rejected",
           actor_account_id=rejecting_account_id,
           target_account_id=inv.sender_account_id,
           invitation_public_id=inv.public_id)
    db.commit()
    db.refresh(inv)
    return inv


def cancel_invitation(
    db: Session, *, public_id: str, sender_account_id: int
) -> BillSplitInvitation:
    inv = get_invitation(db, public_id)
    if sender_account_id != inv.sender_account_id:
        raise AppError("invitation_not_yours", status_code=403)
    if inv.status != "invited":
        # Already terminal — accepted invitations CANNOT be cancelled
        # because the receiver already has a real expense.
        raise AppError("invitation_not_cancellable", status_code=409)
    inv.status = "cancelled"
    inv.cancelled_at = now_utc()
    _audit(db, inv.sender_ledger_id, "bill_split_cancelled",
           actor_account_id=sender_account_id,
           target_account_id=inv.receiver_account_id,
           invitation_public_id=inv.public_id)
    db.commit()
    db.refresh(inv)
    return inv


def expire_invitations(db: Session) -> int:
    """Sweeper: anything ``invited`` with ``expires_at < now`` → expired.

    Returns count of newly-expired rows. Intended to be called from a
    scheduled background task ([[ADR-0030]] handler) or on demand."""
    now = now_utc()
    # SQLAlchemy comparison with TZ-aware datetime on SQLite works for
    # the WHERE clause (server-side string compare is timezone-blind);
    # the values it compares against are stored as naive strings. As long
    # as both we and the DB serialize to ISO-with-Z this is fine.
    pending = list(
        db.scalars(
            select(BillSplitInvitation)
            .where(BillSplitInvitation.status == "invited")
            .where(BillSplitInvitation.expires_at <= now)
        )
    )
    for inv in pending:
        inv.status = "expired"
        inv.expired_at = now
        _audit(db, inv.sender_ledger_id, "bill_split_expired",
               actor_account_id=None,
               target_account_id=inv.receiver_account_id,
               invitation_public_id=inv.public_id)
    if pending:
        db.commit()
    return len(pending)


def _mark_expired(db: Session, inv: BillSplitInvitation) -> None:
    inv.status = "expired"
    inv.expired_at = now_utc()
    _audit(db, inv.sender_ledger_id, "bill_split_expired",
           actor_account_id=None,
           target_account_id=inv.receiver_account_id,
           invitation_public_id=inv.public_id)
    db.commit()


# -------------------------------------------------------------------------
# DTO conversion (Sent / Inbox)


def to_sent_response_dict(inv: BillSplitInvitation) -> dict[str, Any]:
    """Sender view dict. Deliberately omits ``receiver_ledger_id``."""
    return {
        "public_id": inv.public_id,
        "status": inv.status,
        "amount_cents": inv.amount_cents,
        "home_currency_code": inv.home_currency_code,
        "original_currency_code": inv.original_currency_code,
        "original_amount_minor": inv.original_amount_minor,
        "exchange_rate_to_cny": inv.exchange_rate_to_cny,
        "exchange_rate_date": inv.exchange_rate_date,
        "exchange_rate_source": inv.exchange_rate_source,
        "merchant_snapshot": inv.merchant_snapshot,
        "category_suggestion": inv.category_suggestion,
        "expense_time_snapshot": inv.expense_time_snapshot,
        "expires_at": inv.expires_at,
        "created_at": inv.created_at,
        "accepted_at": inv.accepted_at,
        "rejected_at": inv.rejected_at,
        "cancelled_at": inv.cancelled_at,
        "expired_at": inv.expired_at,
        "receiver_account_id": inv.receiver_account_id,
        "receiver_display_name_snapshot": inv.receiver_display_name_snapshot,
        "sender_expense_id": inv.sender_expense_id,
    }


def to_inbox_response_dict(inv: BillSplitInvitation) -> dict[str, Any]:
    """Receiver view dict. Deliberately omits sender's expense_id /
    ledger_id / member_id and receiver's own ledger_id (which is also
    private — receiver may have multiple ledgers)."""
    return {
        "public_id": inv.public_id,
        "status": inv.status,
        "amount_cents": inv.amount_cents,
        "home_currency_code": inv.home_currency_code,
        "original_currency_code": inv.original_currency_code,
        "original_amount_minor": inv.original_amount_minor,
        "exchange_rate_to_cny": inv.exchange_rate_to_cny,
        "exchange_rate_date": inv.exchange_rate_date,
        "exchange_rate_source": inv.exchange_rate_source,
        "merchant_snapshot": inv.merchant_snapshot,
        "category_suggestion": inv.category_suggestion,
        "expense_time_snapshot": inv.expense_time_snapshot,
        "expires_at": inv.expires_at,
        "created_at": inv.created_at,
        "accepted_at": inv.accepted_at,
        "rejected_at": inv.rejected_at,
        "cancelled_at": inv.cancelled_at,
        "expired_at": inv.expired_at,
        "sender_account_id": inv.sender_account_id,
        "sender_display_name": inv.sender_display_name,
    }


# -------------------------------------------------------------------------
# IMMUTABLE_ON_SPLIT_RECEIVED guard helper for update_expense

#: Fields in :class:`Expense` that cannot be modified once the row is a
#: received split (would silently mutate the agreed-upon debt). Updates
#: against any of these on a ``source='bill_split_received'`` expense
#: must raise ``split_received_field_immutable``.
IMMUTABLE_ON_SPLIT_RECEIVED: frozenset[str] = frozenset({
    "amount_cents",
    "original_currency",
    "original_currency_code",
    "original_amount",
    "original_amount_minor",
    "exchange_rate_to_cny",
    "exchange_rate_date",
    "exchange_rate_source",
    "expense_time",
    "spent_at",
    "merchant",
})


def assert_no_immutable_field_changes(
    expense: Expense, changed_fields: set[str]
) -> None:
    """Service-layer guard called by :func:`update_expense`."""
    if expense.source != SPLIT_RECEIVED_SOURCE:
        return
    forbidden = changed_fields & IMMUTABLE_ON_SPLIT_RECEIVED
    if forbidden:
        names = "、".join(sorted(forbidden))
        raise AppError(
            "split_received_field_immutable",
            f"已接受的拆账中以下字段不能修改：{names}。",
            status_code=400,
        )


# -------------------------------------------------------------------------
# Internal helpers


def _display_name(account: Account) -> str:
    name = (account.display_name or "").strip()
    return name or f"account_{account.id}"


def _load_writer_member(
    db: Session, ledger_id: str, account_id: int
) -> LedgerMember:
    """Resolve LedgerMember + verify writer role. 403 if viewer / not member."""
    member = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
    )
    if member is None:
        raise AppError(
            "ledger_forbidden",
            "你不在目标账本，无法操作。",
            status_code=403,
        )
    if member.role not in WRITER_ROLES:
        raise AppError(
            "ledger_forbidden",
            "请选择你有写权限的账本。",
            status_code=403,
        )
    return member


def _audit(
    db: Session,
    ledger_id: str,
    action: str,
    *,
    actor_account_id: int | None,
    target_account_id: int,
    invitation_public_id: str,
) -> None:
    db.add(LedgerAuditLog(
        ledger_id=ledger_id,
        action=action,
        actor_account_id=actor_account_id,
        target_account_id=target_account_id,
        invitation_public_id=invitation_public_id,
        result="success",
    ))


__all__ = [
    "IMMUTABLE_ON_SPLIT_RECEIVED",
    "accept_invitation",
    "assert_no_immutable_field_changes",
    "cancel_invitation",
    "create_invitation",
    "expire_invitations",
    "get_invitation",
    "list_inbox",
    "list_sent",
    "reject_invitation",
    "to_inbox_response_dict",
    "to_sent_response_dict",
]
