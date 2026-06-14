"""ADR-0049 §3.2 / §2.1 true-concurrency for MemberRepaymentProposal.

Two §11 invariants need real independent connections (one shared savepoint
connection cannot model the partial-index wait or the parent-Debt FOR UPDATE
lock contention), so conftest auto-marks these ``test_two_sessions_*`` tests
``real_db`` via the ``::test_two_sessions`` nodeid pattern.

1. The ``uq_mrp_one_pending_per_debt`` partial UNIQUE index is the §3.2
   one-pending-per-Debt backstop: two concurrent creates that both read "no
   pending" (READ COMMITTED hides the other's uncommitted insert) cannot both
   leave a pending row — the second's index insert physically waits on the
   first's uncommitted entry, so it cannot coexist. The service supersede is only
   a workflow convenience; this index is the hard guarantee.
2. The confirm path is fold-changing, so it serializes on the parent Debt's
   ``SELECT ... FOR UPDATE`` (``lock_and_fold``). Two creditors confirming the
   same pending proposal cannot both commit a ``Repayment``: the second blocks
   until the first COMMITs, then re-fetches the proposal under the lock, sees it
   already ``confirmed`` (not ``pending``), and is rejected ``not_pending``.

Mirrors ``test_debt_repayment_concurrency.py`` (holder + ``lock_timeout`` for the
contended wait; serialize-then-recheck for the post-commit state).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal, engine
from app.errors import AppError
from app.models import Account, Debt, LedgerMember, MemberRepaymentProposal, Repayment
from app.schemas import (
    MemberRepaymentProposalConfirmRequest,
    MemberRepaymentProposalCreateRequest,
)
from app.services import debt_service


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_member_account() -> int:
    """A second account, registered as a writer member of the owner ledger."""
    with SessionLocal() as db:
        account = Account(display_name="家人")
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=account.id, role="member"))
        db.commit()
        return account.id


def _seed_member_debt(*, principal_amount_cents: int) -> tuple[str, int, int]:
    """Create + commit one member Debt (owner is creditor; member is debtor).

    ``direction='owed_to_me'`` → the counterparty (member) owes the owner, so the
    member is the debtor (proposer) and the owner is the creditor (confirmer).
    Returns (debt_public_id, debt_row_version, member_account_id).
    """
    owner = _owner_account_id()
    member_id = _seed_member_account()
    with SessionLocal() as db:
        # Public create + the create_debt service reject committed member Debt now
        # (ADR-0049 §5.2 → confirmation flow / bill_split accept); seed the row
        # directly so the proposal concurrency paths have a member Debt to act on.
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner,
            created_by_account_id=owner,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=member_id,
            principal_amount_cents=principal_amount_cents,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id, debt.row_version, member_id


def _create_proposal_via_service(public_id: str, *, debtor_id: int) -> None:
    """Create + commit one pending proposal through the real service path."""
    with SessionLocal() as db:
        debt_service.create_repayment_proposal(
            db,
            tenant_id="owner",
            actor_account_id=debtor_id,
            public_id=public_id,
            payload=MemberRepaymentProposalCreateRequest(proposed_amount_cents=20000),
            idempotency_key=str(uuid4()),
            commit=True,
        )


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="partial-index insert contention is only observable on the "
    "PostgreSQL lane; the partial UNIQUE WHERE predicate is a PG feature",
)
def test_two_sessions_concurrent_proposal_creates_map_to_already_pending(*, identity) -> None:
    """Two debtors race to create the FIRST pending proposal for the same Debt and
    the loser is mapped to ``repayment_proposal_already_pending`` (409) by the
    service — exercising the real ``create_repayment_proposal`` → partial-unique
    IntegrityError → ``begin_nested`` remap, not a raw ORM insert.

    TOCTOU ordering: session B opens a REPEATABLE READ transaction and anchors its
    snapshot with a read BEFORE session A commits its pending proposal. Under that
    frozen snapshot B's ``_current_pending`` check sees NO pending row, so the
    service does not supersede; B's own INSERT then collides with A's now-committed
    row on the ``uq_mrp_one_pending_per_debt`` partial UNIQUE index (the index
    enforces against all physical rows regardless of B's snapshot) → IntegrityError
    → ``begin_nested`` rollback → ``AppError("repayment_proposal_already_pending")``."""
    public_id, _version, member_id = _seed_member_debt(principal_amount_cents=50000)

    # Session B: open a REPEATABLE READ transaction and anchor its snapshot with a
    # read BEFORE A commits. PG takes the snapshot at the first statement, so this
    # read freezes "no pending proposal" into B's view for the rest of its txn.
    blocked = SessionLocal()
    try:
        blocked.connection(
            execution_options={"isolation_level": "REPEATABLE READ"}
        )
        with SessionLocal() as db:
            debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
            debt_id = debt.id
        anchored = list(
            blocked.scalars(
                select(MemberRepaymentProposal)
                .where(MemberRepaymentProposal.debt_id == debt_id)
                .where(MemberRepaymentProposal.status == "pending")
            )
        )
        assert anchored == []  # snapshot anchored: no pending yet

        # Session A: commit the first pending proposal through the service.
        _create_proposal_via_service(public_id, debtor_id=member_id)

        # Session B: its snapshot still sees "no pending", so it does not supersede
        # and inserts its own — colliding on the partial UNIQUE index → 409.
        with pytest.raises(AppError) as exc_info:
            debt_service.create_repayment_proposal(
                blocked,
                tenant_id="owner",
                actor_account_id=member_id,
                public_id=public_id,
                payload=MemberRepaymentProposalCreateRequest(proposed_amount_cents=25000),
                idempotency_key=str(uuid4()),
                commit=True,
            )
        assert exc_info.value.error == "repayment_proposal_already_pending"
        assert exc_info.value.status_code == 409
    finally:
        blocked.rollback()
        blocked.close()

    # Authoritative state: exactly one pending proposal landed (A's).
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        pending = list(
            db.scalars(
                select(MemberRepaymentProposal)
                .where(MemberRepaymentProposal.debt_id == debt.id)
                .where(MemberRepaymentProposal.status == "pending")
            )
        )
        assert len(pending) == 1
        assert pending[0].proposed_amount_cents == 20000


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="parent-Debt FOR UPDATE serialization is only observable on the "
    "PostgreSQL lane; FOR UPDATE is a no-op on SQLite",
)
def test_two_sessions_double_confirm_commits_one_repayment(*, identity) -> None:
    """Serialize-then-recheck: A confirms the proposal FIRST and commits (proposal
    → confirmed, one Repayment, remaining drops). Session B then confirms the
    SAME, now-already-confirmed proposal: this proves the post-commit ``not_pending``
    recheck, not live lock contention — B re-fetches the proposal under
    ``lock_and_fold`` and sees it is no longer ``pending`` so it is rejected
    ``repayment_proposal_not_pending``. (The live FOR-UPDATE blocking is exercised
    separately by ``test_two_sessions_confirm_blocks_on_held_parent_lock``.)
    Exactly one Repayment is committed."""
    public_id, version, member_id = _seed_member_debt(principal_amount_cents=50000)
    owner_id = _owner_account_id()

    # The debtor (member) creates one pending proposal.
    with SessionLocal() as db:
        proposal = debt_service.create_repayment_proposal(
            db,
            tenant_id="owner",
            actor_account_id=member_id,
            public_id=public_id,
            payload=MemberRepaymentProposalCreateRequest(proposed_amount_cents=20000),
            idempotency_key=str(uuid4()),
            commit=True,
        )
        proposal_public_id = proposal.public_id

    # Session A: the creditor confirms — commits one Repayment (remaining 50000 → 30000).
    with SessionLocal() as session_a:
        debt_a = debt_service.confirm_repayment_proposal(
            session_a,
            tenant_id="owner",
            actor_account_id=owner_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
            payload=MemberRepaymentProposalConfirmRequest(expected_row_version=version),
            idempotency_key=str(uuid4()),
            commit=True,
        )
        assert debt_a.remaining_amount_cents == 30000
        assert debt_a.row_version == version + 1

    # Session B: confirming the now-already-confirmed proposal is rejected from
    # the post-lock authoritative state, not double-committed.
    with SessionLocal() as session_b, pytest.raises(AppError) as exc_info:
        debt_service.confirm_repayment_proposal(
            session_b,
            tenant_id="owner",
            actor_account_id=owner_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
            # Use the refreshed version so the stale-intent fence does not
            # pre-empt the not_pending recheck this test targets.
            payload=MemberRepaymentProposalConfirmRequest(expected_row_version=version + 1),
            idempotency_key=str(uuid4()),
            commit=True,
        )
    assert exc_info.value.error == "repayment_proposal_not_pending"

    # Authoritative state: exactly one Repayment, exactly one confirmed proposal.
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert len(repayments) == 1
        assert repayments[0].amount_cents == 20000
        proposals = list(
            db.scalars(
                select(MemberRepaymentProposal).where(
                    MemberRepaymentProposal.debt_id == debt.id
                )
            )
        )
        assert len(proposals) == 1
        assert proposals[0].status == "confirmed"
        assert debt_service.compute_remaining(db, debt) == 30000


def _seed_pending_proposal(public_id: str, *, debtor_id: int) -> str:
    """Create + commit one pending proposal through the service; return its public_id."""
    with SessionLocal() as db:
        proposal = debt_service.create_repayment_proposal(
            db,
            tenant_id="owner",
            actor_account_id=debtor_id,
            public_id=public_id,
            payload=MemberRepaymentProposalCreateRequest(proposed_amount_cents=20000),
            idempotency_key=str(uuid4()),
            commit=True,
        )
        return proposal.public_id


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="parent-Debt FOR UPDATE lock contention is only observable on the "
    "PostgreSQL lane; FOR UPDATE is a no-op on SQLite",
)
def test_two_sessions_confirm_blocks_on_held_parent_lock(*, identity) -> None:
    """Live contention (mirrors ``test_two_sessions_repayment_cannot_both_pass_over_remaining``):
    a holder session takes ``SELECT Debt ... FOR UPDATE`` on the parent Debt and
    stays UNCOMMITTED. A second session sets a short ``lock_timeout`` and calls
    ``confirm_repayment_proposal``: its ``lock_and_fold`` FOR UPDATE on the same
    Debt row physically blocks on the holder's lock, so the short timeout turns the
    contended wait into a deterministic ``OperationalError`` instead of a hang —
    proving B serializes on A's parent-Debt lock, not on a stale snapshot."""
    public_id, version, member_id = _seed_member_debt(principal_amount_cents=50000)
    owner_id = _owner_account_id()
    proposal_public_id = _seed_pending_proposal(public_id, debtor_id=member_id)

    holder = SessionLocal()
    try:
        # Session A holds FOR UPDATE on the parent Debt row, uncommitted.
        holder.scalar(
            select(Debt).where(Debt.public_id == public_id).with_for_update()
        )
        # Session B: the contended FOR UPDATE inside confirm_repayment_proposal's
        # lock_and_fold blocks on A's lock; a short lock_timeout makes that a
        # deterministic fast failure instead of a hang.
        with SessionLocal() as blocked, pytest.raises(OperationalError):
            blocked.execute(text("SET LOCAL lock_timeout = '500ms'"))
            debt_service.confirm_repayment_proposal(
                blocked,
                tenant_id="owner",
                actor_account_id=owner_id,
                public_id=public_id,
                proposal_public_id=proposal_public_id,
                payload=MemberRepaymentProposalConfirmRequest(expected_row_version=version),
                idempotency_key=str(uuid4()),
                commit=True,
            )
    finally:
        holder.rollback()
        holder.close()

    # No Repayment committed (B failed on the lock; A only held a read lock).
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert len(repayments) == 0
        assert debt_service.compute_remaining(db, debt) == 50000
