"""State transitions: accept / reject / cancel / expire (+ _mark_expired)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.fx_constants import FX_SOURCE_BASE, FX_STATUS_READY
from app.models import BillSplitInvitation, Expense, LedgerMember
from app.services.bill_split_service._common import (
    SPLIT_RECEIVED_SOURCE,
    _audit,
    _load_writer_member,
)
from app.services.bill_split_service._query import get_invitation
from app.services.currency_binding_service import resolve_write_capability
from app.services.debt_service import create_bill_split_debt
from app.services.exchange_rate_service import default_rate_date
from app.services.expense_revision_service import record_confirmation_revision
from app.services.time_service import ensure_utc, now_utc


def accept_invitation(
    db: Session,
    *,
    public_id: str,
    accepting_account_id: int,
    target_ledger_id: str,
    accepting_device_id: int | None = None,
) -> tuple[BillSplitInvitation, Expense]:
    """Receiver accepts and binds a received Expense in their chosen ledger.

    Concurrency (ADR-0038 PR-C): the bind is an atomic claim, not a
    SELECT-then-write. The receiver expense is flushed first, then a guarded
    UPDATE flips the invitation from invited to accepted while binding the
    received expense and receiver member fields. Losing races roll back the
    tentative expense and re-resolve the settled invitation idempotently.
    """
    inv = get_invitation(db, public_id)
    _ensure_accepting_receiver(inv, accepting_account_id)

    settled = _resolve_settled_accept(db, inv, target_ledger_id)
    if settled is not None:
        return settled

    # A settled re-accept is a read-only idempotent replay.  Require currency
    # writer authority only after that terminal fast path, before expiry or a
    # new acceptance can mutate persisted facts.
    resolve_write_capability(db)
    settled = _resolve_expired_or_peer_settled_accept(db, public_id, inv, target_ledger_id)
    if settled is not None:
        return settled

    target_member = _load_accept_target_member(
        db,
        inv=inv,
        target_ledger_id=target_ledger_id,
        accepting_account_id=accepting_account_id,
    )
    accepted_at = now_utc()
    received = _build_received_expense(
        inv,
        target_ledger_id=target_ledger_id,
        accepted_at=accepted_at,
    )
    db.add(received)

    lost_accept = _flush_received_expense(db, public_id, target_ledger_id)
    if lost_accept is not None:
        return lost_accept

    if not _claim_invitation_acceptance(
        db,
        inv=inv,
        received_expense_id=received.id,
        target_ledger_id=target_ledger_id,
        target_member_id=target_member.id,
        accepted_at=accepted_at,
    ):
        db.rollback()
        return _resolve_lost_accept(db, public_id, target_ledger_id, None)

    record_confirmation_revision(
        db,
        received,
        actor_account_id=accepting_account_id,
        actor_device_id=accepting_device_id,
    )

    _audit(
        db,
        target_ledger_id,
        "bill_split_accepted",
        actor_account_id=accepting_account_id,
        target_account_id=inv.sender_account_id,
        invitation_public_id=inv.public_id,
    )
    _create_accept_debt_if_enabled(db, inv, target_ledger_id)
    db.commit()
    db.refresh(inv)
    db.refresh(received)
    return inv, received


def _ensure_accepting_receiver(inv: BillSplitInvitation, accepting_account_id: int) -> None:
    # Identity check first; do not leak invitation state to a non-receiver.
    if accepting_account_id != inv.receiver_account_id:
        raise AppError("invitation_not_yours", status_code=403)


def _resolve_expired_or_peer_settled_accept(
    db: Session,
    public_id: str,
    inv: BillSplitInvitation,
    target_ledger_id: str,
) -> tuple[BillSplitInvitation, Expense] | None:
    """Handle accept-time expiry and the race where expiry loses to accept."""
    if ensure_utc(inv.expires_at) > now_utc():
        return None
    if _mark_expired(db, inv):
        raise AppError("invitation_expired", status_code=410)

    fresh = get_invitation(db, public_id)
    if fresh.status == "expired":
        raise AppError("invitation_expired", status_code=410)
    settled = _resolve_settled_accept(db, fresh, target_ledger_id)
    if settled is not None:
        return settled
    raise AppError("server_error", status_code=500)


def _load_accept_target_member(
    db: Session,
    *,
    inv: BillSplitInvitation,
    target_ledger_id: str,
    accepting_account_id: int,
) -> LedgerMember:
    if target_ledger_id == inv.sender_ledger_id:
        raise AppError(
            "ledger_forbidden",
            "不能接受到 sender 的同一个账本。",
            status_code=403,
        )
    return _load_writer_member(db, target_ledger_id, accepting_account_id)


def _build_received_expense(
    inv: BillSplitInvitation,
    *,
    target_ledger_id: str,
    accepted_at: datetime,
) -> Expense:
    """Build the receiver-side expense from the frozen invitation snapshot.

    The receiver owes ``amount_cents`` in HOME currency, so the received row is
    plain home-currency money (original == home, rate == 1). The invitation
    keeps the parent's original-currency snapshot for display.
    """
    return Expense(
        tenant_id=target_ledger_id,
        amount_cents=inv.amount_cents,
        home_currency_code=inv.home_currency_code,
        original_currency_code=inv.home_currency_code,
        original_amount_minor=inv.amount_cents,
        exchange_rate_to_cny=Decimal("1"),
        exchange_rate_date=default_rate_date(inv.expense_time_snapshot),
        exchange_rate_source=FX_SOURCE_BASE,
        fx_status=FX_STATUS_READY,
        merchant=inv.merchant_snapshot,
        category=inv.category_suggestion or "其他",
        note=None,
        source=SPLIT_RECEIVED_SOURCE,
        status="confirmed",
        expense_time=inv.expense_time_snapshot,
        created_at=accepted_at,
        updated_at=accepted_at,
        confirmed_at=accepted_at,
        split_origin_invitation_id=inv.public_id,
    )


def _flush_received_expense(
    db: Session,
    public_id: str,
    target_ledger_id: str,
) -> tuple[BillSplitInvitation, Expense] | None:
    try:
        db.flush()  # Need received.id for invitation.received_expense_id.
    except IntegrityError as exc:  # noqa: BLE001
        # The partial-unique backstop says a peer already created the received
        # expense. Discard ours and resolve against the winner.
        db.rollback()
        return _resolve_lost_accept(db, public_id, target_ledger_id, exc)
    return None


def _claim_invitation_acceptance(
    db: Session,
    *,
    inv: BillSplitInvitation,
    received_expense_id: int,
    target_ledger_id: str,
    target_member_id: int,
    accepted_at: datetime,
) -> bool:
    """Atomically flip invited -> accepted while binding accepted-state fields."""
    rowcount = db.execute(
        update(BillSplitInvitation)
        .where(BillSplitInvitation.id == inv.id)
        .where(BillSplitInvitation.status == "invited")
        .values(
            status="accepted",
            accepted_at=accepted_at,
            received_expense_id=received_expense_id,
            receiver_ledger_id=target_ledger_id,
            receiver_member_id=target_member_id,
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    return rowcount == 1


def _create_accept_debt_if_enabled(db: Session, inv: BillSplitInvitation, target_ledger_id: str) -> None:
    """Create the receiver's member debt in the same transaction when enabled."""
    if not get_settings().debt_rollout_enabled:
        return
    # ADR-0049: accepted expense, invitation claim, and member debt commit
    # together. Re-accept returns before this helper, and uq_debts_source
    # backstops any unexpected race.
    create_bill_split_debt(
        db,
        ledger_id=target_ledger_id,
        receiver_account_id=inv.receiver_account_id,
        sender_account_id=inv.sender_account_id,
        amount_cents=inv.amount_cents,
        home_currency_code=inv.home_currency_code,
        source_invitation_public_id=inv.public_id,
        event_time=inv.expense_time_snapshot,
    )


def _resolve_settled_accept(
    db: Session, inv: BillSplitInvitation, target_ledger_id: str
) -> tuple[BillSplitInvitation, Expense] | None:
    """Interpret an invitation that is no longer freshly acceptable.

    - ``accepted`` -> idempotent re-accept: return the bound expense when the
      target ledger matches, else ``state_conflict``.
    - any other terminal status -> ``invitation_not_acceptable``.
    - ``invited`` -> ``None`` (caller proceeds to accept).

    Pure read + raise; never commits. Shared by the fast-path pre-check and
    the post-rollback recovery so both read a settled invitation identically.
    """
    if inv.status == "accepted":
        if inv.receiver_ledger_id != target_ledger_id:
            raise AppError("state_conflict", status_code=409)
        if inv.received_expense_id is None or inv.receiver_ledger_id is None:
            # Should be impossible (the claim binds both atomically), but guard.
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
    return None


def _resolve_lost_accept(
    db: Session,
    public_id: str,
    target_ledger_id: str,
    cause: Exception | None,
) -> tuple[BillSplitInvitation, Expense]:
    """Recover after a peer accept won the claim or partial-unique race."""
    inv = get_invitation(db, public_id)
    if inv.status == "expired":
        raise AppError("invitation_expired", status_code=410) from cause
    settled = _resolve_settled_accept(db, inv, target_ledger_id)
    if settled is not None:
        return settled
    raise AppError("server_error", status_code=500) from cause


def reject_invitation(db: Session, *, public_id: str, rejecting_account_id: int) -> BillSplitInvitation:
    resolve_write_capability(db)
    inv = get_invitation(db, public_id)
    if rejecting_account_id != inv.receiver_account_id:
        raise AppError("invitation_not_yours", status_code=403)
    inv = _settle_expiry_before_transition(db, public_id, inv)
    if inv.status != "invited":
        raise AppError("invitation_not_acceptable", status_code=409)
    # Atomic flip (mirrors the accept claim): only reject while still
    # 'invited', so a peer accept that won between our status read and this
    # write can never be clobbered to 'rejected'.
    rowcount = db.execute(
        update(BillSplitInvitation)
        .where(BillSplitInvitation.id == inv.id)
        .where(BillSplitInvitation.status == "invited")
        .values(status="rejected", rejected_at=now_utc())
        .execution_options(synchronize_session=False)
    ).rowcount
    if rowcount != 1:
        # A peer settled the invitation first; same outcome as having read
        # the settled row up front.
        db.rollback()
        _raise_lost_non_accept(db, public_id, "invitation_not_acceptable")
    _audit(
        db,
        inv.sender_ledger_id,
        "bill_split_rejected",
        actor_account_id=None,
        target_account_id=rejecting_account_id,
        invitation_public_id=inv.public_id,
    )
    db.commit()
    db.refresh(inv)
    return inv


def cancel_invitation(db: Session, *, public_id: str, sender_account_id: int) -> BillSplitInvitation:
    resolve_write_capability(db)
    inv = get_invitation(db, public_id)
    if sender_account_id != inv.sender_account_id:
        raise AppError("invitation_not_yours", status_code=403)
    _load_writer_member(db, inv.sender_ledger_id, sender_account_id)
    inv = _settle_expiry_before_transition(db, public_id, inv)
    if inv.status != "invited":
        # Already terminal; accepted invitations cannot be cancelled because
        # the receiver already has a real expense.
        raise AppError("invitation_not_cancellable", status_code=409)
    # Atomic flip (mirrors the accept claim): a sender cancel racing a receiver
    # accept must lose once the accept claim lands.
    rowcount = db.execute(
        update(BillSplitInvitation)
        .where(BillSplitInvitation.id == inv.id)
        .where(BillSplitInvitation.status == "invited")
        .values(status="cancelled", cancelled_at=now_utc())
        .execution_options(synchronize_session=False)
    ).rowcount
    if rowcount != 1:
        db.rollback()
        _raise_lost_non_accept(db, public_id, "invitation_not_cancellable")
    _audit(
        db,
        inv.sender_ledger_id,
        "bill_split_cancelled",
        actor_account_id=sender_account_id,
        target_account_id=inv.receiver_account_id,
        invitation_public_id=inv.public_id,
    )
    db.commit()
    db.refresh(inv)
    return inv


def _raise_lost_non_accept(db: Session, public_id: str, default_error: str) -> None:
    """Report the canonical winner after a reject/cancel claim loses."""
    if get_invitation(db, public_id).status == "expired":
        raise AppError("invitation_expired", status_code=410)
    raise AppError(default_error, status_code=409)


def _settle_expiry_before_transition(
    db: Session,
    public_id: str,
    inv: BillSplitInvitation,
) -> BillSplitInvitation:
    """Make the command-time TTL boundary authoritative for every action."""
    if ensure_utc(inv.expires_at) > now_utc():
        return inv
    if _mark_expired(db, inv):
        raise AppError("invitation_expired", status_code=410)

    fresh = get_invitation(db, public_id)
    if fresh.status == "expired":
        raise AppError("invitation_expired", status_code=410)
    return fresh


def expire_invitations(db: Session) -> int:
    """Sweeper: anything ``invited`` with ``expires_at < now`` -> expired.

    A single guarded ``UPDATE ... WHERE status='invited' ... RETURNING`` means
    a row concurrently accepted/rejected/cancelled after an earlier read can
    never be clobbered to expired.
    """
    now = now_utc()
    candidate_id = db.scalar(
        select(BillSplitInvitation.id)
        .where(BillSplitInvitation.status == "invited")
        .where(BillSplitInvitation.expires_at < now)
        .limit(1)
    )
    if candidate_id is None:
        return 0
    resolve_write_capability(db)
    expired = db.execute(
        update(BillSplitInvitation)
        .where(BillSplitInvitation.status == "invited")
        .where(BillSplitInvitation.expires_at <= now)
        .values(status="expired", expired_at=now)
        .returning(
            BillSplitInvitation.sender_ledger_id,
            BillSplitInvitation.receiver_account_id,
            BillSplitInvitation.public_id,
        )
        .execution_options(synchronize_session=False)
    ).all()
    for row in expired:
        _audit(
            db,
            row.sender_ledger_id,
            "bill_split_expired",
            actor_account_id=None,
            target_account_id=row.receiver_account_id,
            invitation_public_id=row.public_id,
        )
    if expired:
        db.commit()
    return len(expired)


def _mark_expired(db: Session, inv: BillSplitInvitation) -> bool:
    """Best-effort expiry flip; false means a peer settled the row first."""
    resolve_write_capability(db)
    rowcount = db.execute(
        update(BillSplitInvitation)
        .where(BillSplitInvitation.id == inv.id)
        .where(BillSplitInvitation.status == "invited")
        .values(status="expired", expired_at=now_utc())
        .execution_options(synchronize_session=False)
    ).rowcount
    if rowcount != 1:
        db.rollback()
        return False
    _audit(
        db,
        inv.sender_ledger_id,
        "bill_split_expired",
        actor_account_id=None,
        target_account_id=inv.receiver_account_id,
        invitation_public_id=inv.public_id,
    )
    db.commit()
    return True
