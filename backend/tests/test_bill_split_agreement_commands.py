"""Actual PostgreSQL agreement commands: waivers, party authority and stale terms."""

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import BillSplitAgreementChange, Debt, DebtForgiveness
from app.services.debt_service._fold import compute_paid, compute_remaining
from tests.bill_split_test_support import WHEN
from tests.bill_split_test_support import accept_agreement_change as _accept
from tests.bill_split_test_support import agreement_db as agreement_db
from tests.bill_split_test_support import record_agreement_payment as _paid
from tests.bill_split_test_support import request_agreement_change as _request


def test_existing_forgiveness_survives_a_new_agreement_without_fake_cash(agreement_db):
    db, split = agreement_db
    _paid(db, split, split["original_id"], 1_000)
    db.add(DebtForgiveness(debt_id=split["original_id"], amount_cents=3_000, actor_account_id=split["sender_id"],
        idempotency_key="gift", created_at=WHEN))
    db.flush()
    proposal = _request(db, split, share=2_000, net=0)
    _accept(db, split, proposal)
    assert proposal.original_forgiven_amount_cents == 3_000
    assert compute_remaining(db, db.get(Debt, split["original_id"])) == 0
    assert compute_paid(db, db.get(Debt, split["original_id"])) == 1_000
    assert db.scalar(select(Debt).where(Debt.source_type == "bill_split_return")) is None


def test_proposer_cannot_accept_own_terms_and_stale_other_party_must_review_again(agreement_db):
    db, split = agreement_db
    proposal = _request(db, split, share=2_000, net=2_000)
    with pytest.raises(AppError) as own:
        _accept(db, split, proposal, actor="receiver")
    assert own.value.error == "split_change_other_party_only"
    db.get(Debt, split["original_id"]).row_version += 1
    db.flush()
    with pytest.raises(AppError) as stale:
        _accept(db, split, proposal)
    assert stale.value.error == "state_conflict"
    assert proposal.status == "pending"
    assert not list(db.scalars(select(BillSplitAgreementChange)))


def test_same_ledger_reader_cannot_change_another_members_agreement(agreement_db):
    db, split = agreement_db
    with pytest.raises(AppError) as denied:
        _request(db, split, share=2_000, net=2_000, actor="viewer")
    assert denied.value.error == "split_change_party_only"
