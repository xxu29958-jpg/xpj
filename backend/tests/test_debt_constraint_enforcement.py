"""ADR-0049 #4: the member-repayment FK + status-consistency CHECK backstops actually
REJECT dirty data — not merely exist (that's the alembic round-trip test). This proves the
DB fails fast on the lifecycle invariants the service already maintains, so a future service
bug producing e.g. a ``confirmed`` proposal with no committed Repayment, or a committed
back-link pointing at a missing row, is stopped at the DB rather than silently corrupting the
fold. ``ADD CONSTRAINT`` in the migration runs the same validation on existing PROD rows, so
these also stand in for "the migration fails fast on dirty data".

Each violation is attempted in a ``begin_nested`` savepoint so the IntegrityError rolls back
just that savepoint, not the per-test transaction.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Debt, MemberRepaymentProposal, Repayment, RepaymentDraft
from app.services.time_service import now_utc
from tests.debt_proposal_helpers import (
    _create_member_debt,
    _member_headers,
    _mint_member_actor,
    _propose,
)
from tests.test_repayment_drafts import _create_draft


def _seed_pending_proposal(client: TestClient, owner_headers: dict[str, str]) -> tuple[int, int, int]:
    """Create a member Debt + one pending proposal; return (proposal_id, debt_id, owner_account_id)."""
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, owner_headers, direction="owed_to_me", member_account_id=member_id
    )
    resp = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    )
    assert resp.status_code == 201, resp.json()
    proposal_public_id = resp.json()["public_id"]
    with SessionLocal() as db:
        return db.execute(
            select(
                MemberRepaymentProposal.id,
                Debt.id,
                Debt.owner_account_id,
            )
            .join(Debt, Debt.id == MemberRepaymentProposal.debt_id)
            .where(MemberRepaymentProposal.public_id == proposal_public_id)
        ).one()


def _insert_repayment(debt_id: int, actor_account_id: int) -> int:
    with SessionLocal() as db:
        rep = Repayment(
            debt_id=debt_id,
            amount_cents=100,
            paid_at=now_utc(),
            actor_account_id=actor_account_id,
            idempotency_key=str(uuid4()),
        )
        db.add(rep)
        db.commit()
        return rep.id


def _expect_integrity_error(sql: str, params: dict) -> None:
    # begin_nested() is innermost so its __exit__ rolls the savepoint back and re-raises;
    # pytest.raises (one level out) then catches the re-raised IntegrityError.
    with SessionLocal() as db, pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(sql), params)
        db.flush()


def test_committed_check_rejects_confirmed_without_committed_repayment(
    client: TestClient, *, identity
) -> None:
    # status -> confirmed while committed_repayment_id stays NULL violates
    # ck_mrp_committed_iff_confirmed (forward). confirmed_amount set so ONLY the committed
    # CHECK fires, isolating it from the amount CHECK.
    proposal_id, _debt_id, _owner = _seed_pending_proposal(client, identity.app_headers)
    _expect_integrity_error(
        "UPDATE member_repayment_proposals "
        "SET status='confirmed', confirmed_amount_cents=100 WHERE id=:i",
        {"i": proposal_id},
    )


def test_committed_check_rejects_committed_repayment_on_pending_status(
    client: TestClient, *, identity
) -> None:
    # A real (FK-valid) committed_repayment_id on a still-pending proposal violates
    # ck_mrp_committed_iff_confirmed (reverse) — the FK is satisfied, so the CHECK fails.
    proposal_id, debt_id, owner = _seed_pending_proposal(client, identity.app_headers)
    rep_id = _insert_repayment(debt_id, owner)
    _expect_integrity_error(
        "UPDATE member_repayment_proposals SET committed_repayment_id=:r WHERE id=:i",
        {"r": rep_id, "i": proposal_id},
    )


def test_confirmed_amount_check_rejects_confirmed_without_amount(
    client: TestClient, *, identity
) -> None:
    # status -> confirmed with a real committed repayment but NULL confirmed_amount_cents
    # violates ck_mrp_confirmed_amount_iff_confirmed (the committed CHECK is satisfied).
    proposal_id, debt_id, owner = _seed_pending_proposal(client, identity.app_headers)
    rep_id = _insert_repayment(debt_id, owner)
    _expect_integrity_error(
        "UPDATE member_repayment_proposals "
        "SET status='confirmed', committed_repayment_id=:r WHERE id=:i",
        {"r": rep_id, "i": proposal_id},
    )


def test_committed_repayment_fk_rejects_orphan(client: TestClient, *, identity) -> None:
    # A committed_repayment_id pointing at a non-existent repayment violates
    # fk_mrp_committed_repayment (both CHECKs satisfied: confirmed + committed + amount set).
    proposal_id, _debt_id, _owner = _seed_pending_proposal(client, identity.app_headers)
    _expect_integrity_error(
        "UPDATE member_repayment_proposals "
        "SET status='confirmed', committed_repayment_id=999999999, "
        "confirmed_amount_cents=100 WHERE id=:i",
        {"i": proposal_id},
    )


def test_repayment_proposal_id_fk_rejects_orphan(client: TestClient, *, identity) -> None:
    # repayments.proposal_id pointing at a non-existent proposal violates fk_repayments_proposal.
    _proposal_id, debt_id, owner = _seed_pending_proposal(client, identity.app_headers)
    rep_id = _insert_repayment(debt_id, owner)
    _expect_integrity_error(
        "UPDATE repayments SET proposal_id=999999999 WHERE id=:i", {"i": rep_id}
    )


def test_supersedes_proposal_id_fk_rejects_orphan(client: TestClient, *, identity) -> None:
    # The self-ref supersedes_proposal_id pointing at a non-existent proposal violates
    # fk_mrp_supersedes_proposal.
    proposal_id, _debt_id, _owner = _seed_pending_proposal(client, identity.app_headers)
    _expect_integrity_error(
        "UPDATE member_repayment_proposals SET supersedes_proposal_id=999999999 WHERE id=:i",
        {"i": proposal_id},
    )


def _seed_pending_draft(client: TestClient, identity) -> int:
    draft = _create_draft(client, identity)
    with SessionLocal() as db:
        return db.scalar(
            select(RepaymentDraft.id).where(RepaymentDraft.public_id == draft["public_id"])
        )


def test_draft_check_rejects_confirmed_without_committed(client: TestClient, *, identity) -> None:
    # A RepaymentDraft flipped to 'confirmed' without a committed_repayment_public_id violates
    # ck_repayment_drafts_committed_iff_confirmed (forward).
    draft_id = _seed_pending_draft(client, identity)
    _expect_integrity_error(
        "UPDATE repayment_drafts SET status='confirmed' WHERE id=:i", {"i": draft_id}
    )


def test_draft_check_rejects_committed_on_pending(client: TestClient, *, identity) -> None:
    # A committed_repayment_public_id on a still-pending draft violates the same CHECK (reverse).
    draft_id = _seed_pending_draft(client, identity)
    _expect_integrity_error(
        "UPDATE repayment_drafts SET committed_repayment_public_id='x' WHERE id=:i",
        {"i": draft_id},
    )
