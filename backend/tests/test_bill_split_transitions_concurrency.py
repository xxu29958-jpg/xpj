"""Current invitation commands preserve committed acceptance and canonical expiry
across connections; stale reads cannot overwrite a peer's terminal result.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update

from app.database import SessionLocal
from app.errors import AppError
from app.models import BillSplitInvitation, Expense, LedgerAuditLog
from app.services import bill_split_service as bsplit
from app.services.bill_split_service import _create as create_impl
from app.services.bill_split_service import _transitions as transition_impl
from app.services.bill_split_service._transitions import _mark_expired
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc
from tests._infra.identity import seeded_owner_account_id
from tests.bill_split_test_support import _make_expense_for_owner, _seed_receiver


def _backdate_expiry(public_id: str) -> None:
    """Force an invitation's TTL into the past directly in the DB."""
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.execute(
            update(BillSplitInvitation)
            .where(BillSplitInvitation.public_id == public_id)
            .values(expires_at=now_utc() - timedelta(days=1))
        )
        db.commit()


def _create_invitation_for_race(*, receiver_account_id: int, amount_cents: int = 2500) -> str:
    expense_id = _make_expense_for_owner(amount_cents=5000)
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=seeded_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=amount_cents,
            idempotency_key=str(uuid4()), expected_row_version=1,
        )
        return inv.public_id


def _expire_from_peer(public_id: str) -> None:
    """Cross the TTL and run the command expiry transition from another session."""
    _backdate_expiry(public_id)
    with SessionLocal() as peer:
        assert _mark_expired(peer, bsplit.get_invitation(peer, public_id))


def _assert_one_expiry(public_id: str) -> None:
    with SessionLocal() as db:
        inv = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert inv is not None and inv.status == "expired"
        audits = list(
            db.scalars(
                select(LedgerAuditLog)
                .where(LedgerAuditLog.invitation_public_id == public_id)
                .where(LedgerAuditLog.action == "bill_split_expired")
            )
        )
        assert len(audits) == 1


@pytest.mark.real_db
def test_accept_lost_to_peer_expiry_reports_canonical_expiry(monkeypatch, *, identity) -> None:
    receiver_account_id = _seed_receiver(name="B-accept-expiry", ledger_id="receiver_accept_expiry")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)
    load_member = transition_impl._load_accept_target_member

    monkeypatch.setattr(
        transition_impl,
        "_resolve_expired_or_peer_settled_accept",
        lambda _db, _public_id, _inv, _target_ledger_id: None,
    )

    def load_then_expire(db, **kwargs):
        member = load_member(db, **kwargs)
        _expire_from_peer(public_id)
        return member

    monkeypatch.setattr(transition_impl, "_load_accept_target_member", load_then_expire)

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_accept_expiry",
        )
    assert exc.value.error == "invitation_expired"
    assert exc.value.status_code == 410
    _assert_one_expiry(public_id)


@pytest.mark.real_db
@pytest.mark.parametrize("command", ["reject", "cancel"])
def test_non_accept_transition_lost_to_peer_expiry_reports_canonical_expiry(monkeypatch, *, identity, command: str) -> None:
    receiver_account_id = _seed_receiver(name=f"B-{command}-expiry", ledger_id=f"receiver_{command}_expiry")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)

    def expire_after_live_precheck(_db, _public_id, inv):
        _expire_from_peer(public_id)
        return inv

    monkeypatch.setattr(transition_impl, "_settle_expiry_before_transition", expire_after_live_precheck)

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        if command == "reject":
            bsplit.reject_invitation(
                db,
                public_id=public_id,
                rejecting_account_id=receiver_account_id,
            )
        else:
            bsplit.cancel_invitation(
                db,
                public_id=public_id,
                sender_account_id=seeded_owner_account_id(),
            )
    assert exc.value.error == "invitation_expired"
    assert exc.value.status_code == 410
    _assert_one_expiry(public_id)


@pytest.mark.real_db
def test_two_sessions_reject_vs_accept_race_does_not_clobber_accepted(*, identity) -> None:
    """session_b holds a stale 'invited' read of an invitation; session_a
    accepts and commits; session_b's reject must lose to the guarded flip
    (409) instead of overwriting the accepted row — the receiver's confirmed
    expense and the invitation status stay consistent."""
    receiver_account_id = _seed_receiver(name="B-rejrace", ledger_id="receiver_rejrace")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_b = session_b.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert row_b is not None and row_b.status == "invited"

        bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_rejrace",
        )

        with pytest.raises(AppError) as exc:
            bsplit.reject_invitation(
                session_b,
                public_id=public_id,
                rejecting_account_id=receiver_account_id,
            )
        assert exc.value.error == "invitation_not_acceptable"
        assert exc.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    with SessionLocal() as db:
        inv = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert inv is not None
        assert inv.status == "accepted"
        assert inv.rejected_at is None
        received = db.scalar(select(Expense).where(Expense.split_origin_invitation_id == public_id))
        assert received is not None and received.status == "confirmed"


@pytest.mark.real_db
def test_two_sessions_cancel_vs_accept_race_does_not_clobber_accepted(*, identity) -> None:
    """The audited defect: sender cancel racing receiver accept. Once the
    accept claim lands, the receiver holds a confirmed expense whose money
    fields are frozen — a stale-read cancel overwriting status to 'cancelled'
    would leave debt the sender believes was withdrawn. The guarded flip must
    make the cancel lose with 409."""
    receiver_account_id = _seed_receiver(name="B-canrace", ledger_id="receiver_canrace")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_b = session_b.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert row_b is not None and row_b.status == "invited"

        bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_canrace",
        )

        with pytest.raises(AppError) as exc:
            bsplit.cancel_invitation(
                session_b,
                public_id=public_id,
                sender_account_id=seeded_owner_account_id(),
            )
        assert exc.value.error == "invitation_not_cancellable"
        assert exc.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    with SessionLocal() as db:
        inv = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert inv is not None
        assert inv.status == "accepted"
        assert inv.cancelled_at is None


@pytest.mark.real_db
def test_two_sessions_mark_expired_loses_to_settled_invitation(*, identity) -> None:
    """``_mark_expired`` only flips rows still 'invited': against a stale
    snapshot of a row that has since been accepted it reports ``False`` and
    writes nothing (no status clobber, no bill_split_expired audit row)."""
    receiver_account_id = _seed_receiver(name="B-exprace", ledger_id="receiver_exprace")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_b = session_b.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert row_b is not None and row_b.status == "invited"

        bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_exprace",
        )

        assert _mark_expired(session_b, row_b) is False
    finally:
        session_a.close()
        session_b.close()

    with SessionLocal() as db:
        inv = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert inv is not None
        assert inv.status == "accepted"
        assert inv.expired_at is None
        expired_audit = list(
            db.scalars(
                select(LedgerAuditLog)
                .where(LedgerAuditLog.invitation_public_id == public_id)
                .where(LedgerAuditLog.action == "bill_split_expired")
            )
        )
        assert expired_audit == []


def test_accept_after_ttl_marks_expired_and_returns_410(*, identity) -> None:
    receiver_account_id = _seed_receiver(name="B-ttl", ledger_id="receiver_ttl")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)
    _backdate_expiry(public_id)

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_ttl",
        )
    assert exc.value.error == "invitation_expired"
    assert exc.value.status_code == 410

    with SessionLocal() as db:
        inv = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert inv is not None
        assert inv.status == "expired"
        assert inv.expired_at is not None


def test_reject_after_ttl_marks_expired_and_returns_410(*, identity) -> None:
    receiver_account_id = _seed_receiver(name="B-ttl-reject", ledger_id="receiver_ttl_reject")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)
    _backdate_expiry(public_id)

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bsplit.reject_invitation(
            db,
            public_id=public_id,
            rejecting_account_id=receiver_account_id,
        )
    assert exc.value.error == "invitation_expired"
    assert exc.value.status_code == 410

    with SessionLocal() as db:
        inv = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert inv is not None
        assert inv.status == "expired"
        assert inv.expired_at is not None
        assert inv.rejected_at is None


def test_cancel_after_ttl_marks_expired_and_returns_410(*, identity) -> None:
    receiver_account_id = _seed_receiver(name="B-ttl-cancel", ledger_id="receiver_ttl_cancel")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)
    _backdate_expiry(public_id)

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bsplit.cancel_invitation(
            db,
            public_id=public_id,
            sender_account_id=seeded_owner_account_id(),
        )
    assert exc.value.error == "invitation_expired"
    assert exc.value.status_code == 410

    with SessionLocal() as db:
        inv = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        assert inv is not None
        assert inv.status == "expired"
        assert inv.expired_at is not None
        assert inv.cancelled_at is None


@pytest.mark.real_db
def test_accept_claim_wins_while_new_invitation_waits_across_ttl(monkeypatch, identity):
    receiver = _seed_receiver(name="TTL winner", ledger_id="ttl_winner")
    public_id = _create_invitation_for_race(receiver_account_id=receiver, amount_cents=5000)
    with SessionLocal() as db:
        invitation = bsplit.get_invitation(db, public_id)
        source_id = invitation.sender_expense_id
        deadline = invitation.expires_at
    source_locked, accepted_claim, finish_accept, past_deadline = Event(), Event(), Event(), Event()
    pids = {}
    load_parent, claim_accept = create_impl._load_split_parent_expense, transition_impl._claim_invitation_acceptance

    def load_and_hold_source(db, **kwargs):
        parent = load_parent(db, **kwargs)
        pids["create"] = db.scalar(text("SELECT pg_backend_pid()"))
        source_locked.set()
        assert accepted_claim.wait(10), "accept did not reach its invitation claim"
        return parent

    def claim_and_hold_accept(db, **kwargs):
        claimed = claim_accept(db, **kwargs)
        assert claimed
        pids["accept"] = db.scalar(text("SELECT pg_backend_pid()"))
        past_deadline.set()
        accepted_claim.set()
        assert finish_accept.wait(10), "accept continuation was not released"
        return claimed

    def create_competing():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            bsplit.create_invitation(db, sender_account_id=seeded_owner_account_id(), sender_ledger_id="owner",
                expense_id=source_id, receiver_account_id=receiver, amount_cents=1000,
                idempotency_key=str(uuid4()), expected_row_version=1)

    def accept_original():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            _, received = bsplit.accept_invitation(db, public_id=public_id,
                accepting_account_id=receiver, target_ledger_id="ttl_winner")
            return received.id

    monkeypatch.setattr(create_impl, "_load_split_parent_expense", load_and_hold_source)
    monkeypatch.setattr(transition_impl, "_claim_invitation_acceptance", claim_and_hold_accept)
    monkeypatch.setattr(transition_impl, "now_utc", lambda: deadline + timedelta(seconds=1)
        if past_deadline.is_set() else deadline - timedelta(seconds=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        creating = pool.submit(create_competing)
        try:
            assert source_locked.wait(10)
            accepting = pool.submit(accept_original)
            assert accepted_claim.wait(10)
            with SessionLocal() as observer:
                stop = monotonic() + 5
                while monotonic() < stop:
                    blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["create"]})
                    if pids["accept"] in blockers:
                        break
                    sleep(0.01)
                assert pids["accept"] in blockers, "new invitation never waited on the acceptance claim"
        finally:
            finish_accept.set()
        received_id = accepting.result(timeout=10)
        with pytest.raises(AppError, match="拆账邀请总额") as error:
            creating.result(timeout=10)
        assert error.value.error == "split_total_exceeds_parent"
    with SessionLocal() as db:
        invitation = bsplit.get_invitation(db, public_id)
        assert invitation.status == "accepted" and invitation.received_expense_id == received_id
        assert invitation.expired_at is None
        assert len(list(db.scalars(select(BillSplitInvitation).where(BillSplitInvitation.sender_expense_id == source_id)))) == 1
        assert list(db.scalars(select(LedgerAuditLog).where(
            LedgerAuditLog.invitation_public_id == public_id, LedgerAuditLog.action == "bill_split_expired"))) == []


@pytest.mark.real_db
def test_new_invitation_expiry_wins_after_accept_passed_its_deadline_check(monkeypatch, identity):
    receiver = _seed_receiver(name="TTL loser", ledger_id="ttl_loser")
    public_id = _create_invitation_for_race(receiver_account_id=receiver, amount_cents=5000)
    load_member = transition_impl._load_accept_target_member
    replacement_ids = []

    def load_then_replace(db, **kwargs):
        member = load_member(db, **kwargs)
        _backdate_expiry(public_id)
        with SessionLocal() as peer:
            old = bsplit.get_invitation(peer, public_id)
            replacement = bsplit.create_invitation(peer, sender_account_id=old.sender_account_id,
                sender_ledger_id=old.sender_ledger_id, expense_id=old.sender_expense_id,
                receiver_account_id=receiver, amount_cents=5000, idempotency_key=str(uuid4()), expected_row_version=1)
            replacement_ids.append(replacement.public_id)
        return member

    monkeypatch.setattr(transition_impl, "_load_accept_target_member", load_then_replace)
    with SessionLocal() as db, pytest.raises(AppError) as error:
        bsplit.accept_invitation(db, public_id=public_id, accepting_account_id=receiver, target_ledger_id="ttl_loser")
    assert error.value.error == "invitation_expired" and error.value.status_code == 410
    _assert_one_expiry(public_id)
    with SessionLocal() as db:
        assert db.scalar(select(Expense).where(Expense.split_origin_invitation_id == public_id)) is None
        assert len(replacement_ids) == 1
        assert bsplit.get_invitation(db, replacement_ids[0]).status == "invited"
