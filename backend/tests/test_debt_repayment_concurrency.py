"""ADR-0049 §2.1 / F8 true-concurrency: two repayments cannot both pass an
over-remaining fold check.

These ``test_two_sessions_*`` tests need real independent connections (one shared
savepoint connection cannot model FOR UPDATE lock contention), so conftest
auto-marks them ``real_db`` via the ``::test_two_sessions`` nodeid pattern.

The §2.1 serialization武器 is ``lock_and_fold``'s ``SELECT Debt ... FOR UPDATE``:
a second writer physically blocks until the first COMMITs, then recomputes
``remaining`` from facts that include the first repayment and rejects its own
overpay. This mirrors ``test_bill_split_hardening.test_create_invitation_row_locks_parent_expense``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal, engine
from app.models import Account, Debt, Repayment
from app.schemas import DebtCreateRequest, RepaymentCreateRequest
from app.services import debt_service


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_committed_debt(*, principal_amount_cents: int) -> tuple[str, int]:
    """Create + commit one external Debt; return (public_id, row_version)."""
    actor = _owner_account_id()
    with SessionLocal() as db:
        debt = debt_service.create_debt(
            db,
            tenant_id="owner",
            created_by_account_id=actor,
            owner_account_id=actor,
            payload=DebtCreateRequest(
                direction="i_owe",
                counterparty_type="external",
                counterparty_label="信用卡",
                principal_amount_cents=principal_amount_cents,
            ),
            commit=True,
        )
        return debt.public_id, debt.row_version


def _repayment_payload(amount_cents: int, expected_row_version: int) -> RepaymentCreateRequest:
    return RepaymentCreateRequest(
        amount_cents=amount_cents,
        expected_row_version=expected_row_version,
    )


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="row-lock contention is only observable on the PostgreSQL lane; "
    "FOR UPDATE is a no-op on SQLite",
)
def test_two_sessions_repayment_cannot_both_pass_over_remaining(*, identity) -> None:
    """Principal 100; session A holds the parent FOR UPDATE while recording a 60
    repayment without committing. Session B's repayment of 60 cannot complete:
    its ``lock_and_fold`` FOR UPDATE on the same Debt blocks on A's lock, and a
    short ``lock_timeout`` turns that into a deterministic ``OperationalError``
    instead of a hang. Only one of the two 60s can ever land."""
    public_id, version = _seed_committed_debt(principal_amount_cents=10000)
    actor = _owner_account_id()

    holder = SessionLocal()
    try:
        # Session A acquires and holds FOR UPDATE on the parent Debt row.
        holder.scalar(
            select(Debt).where(Debt.public_id == public_id).with_for_update()
        )
        # Session B: a short lock_timeout turns the contended FOR UPDATE inside
        # record_repayment into a deterministic fast failure instead of a hang.
        with SessionLocal() as blocked, pytest.raises(OperationalError):
            blocked.execute(text("SET LOCAL lock_timeout = '500ms'"))
            debt_service.record_repayment(
                blocked,
                tenant_id="owner",
                public_id=public_id,
                actor_account_id=actor,
                payload=_repayment_payload(6000, version),
                idempotency_key=str(uuid4()),
                commit=True,
            )
    finally:
        holder.rollback()
        holder.close()


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="serialized recheck is only observable on the PostgreSQL lane",
)
def test_two_sessions_repayment_serializes_then_second_rechecks(*, identity) -> None:
    """A commits a 60 repayment first (remaining 100 → 40). B then records a 60
    against the now-serialized state: its post-lock fold sees remaining=40 and
    rejects the 60 as overpay rather than double-spending."""
    public_id, version = _seed_committed_debt(principal_amount_cents=10000)
    actor = _owner_account_id()

    # Session A: commit a 60 repayment.
    with SessionLocal() as session_a:
        debt_a = debt_service.record_repayment(
            session_a,
            tenant_id="owner",
            public_id=public_id,
            actor_account_id=actor,
            payload=_repayment_payload(6000, version),
            idempotency_key=str(uuid4()),
            commit=True,
        )
        assert debt_a.row_version == version + 1

    # Session B: the same 60 must now be rejected from authoritative facts.
    from app.errors import AppError

    with SessionLocal() as session_b, pytest.raises(AppError) as exc_info:
        debt_service.record_repayment(
            session_b,
            tenant_id="owner",
            public_id=public_id,
            actor_account_id=actor,
            # B reuses the now-stale original version on purpose: even ignoring
            # the stale-intent fence, the overpay check rejects it. Use the
            # refreshed version to isolate the overpay path.
            payload=_repayment_payload(6000, version + 1),
            idempotency_key=str(uuid4()),
            commit=True,
        )
    assert exc_info.value.error == "debt_overpay_rejected"

    # Authoritative state: exactly one 60 landed.
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        assert debt is not None
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert len(repayments) == 1
        assert repayments[0].amount_cents == 6000
        assert debt_service.compute_remaining(db, debt) == 4000
