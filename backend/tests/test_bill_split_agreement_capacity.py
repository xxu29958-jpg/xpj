"""New agreements and new invitations consume the same source share capacity."""

from datetime import timedelta

import pytest

from app.errors import AppError
from app.models import BillSplitInvitation, Debt, Expense
from app.services.bill_split_service._create import _ensure_invitation_capacity
from app.services.time_service import now_utc
from tests.test_bill_split_agreement_commands import _accept, _request
from tests.test_bill_split_agreement_commands import agreement_db as agreement_db


def test_lower_accepted_share_releases_capacity_without_rewriting_original_invitation(agreement_db):
    db = agreement_db
    _accept(db, _request(db, share=2_000, net=2_000))
    _ensure_invitation_capacity(db, expense=db.get(Expense, 100), receiver_account_id=3, amount_cents=8_000)
    assert db.get(BillSplitInvitation, 1).amount_cents == 4_000


def test_pending_invitation_reservation_prevents_another_agreement_overallocating_source(agreement_db):
    db = agreement_db
    db.add(BillSplitInvitation(public_id="reserved", sender_account_id=2, sender_ledger_id="sender-private",
        sender_expense_id=100, receiver_account_id=3, amount_cents=4_000, home_currency_code="CNY",
        status="invited", created_at=now_utc(), expires_at=now_utc() + timedelta(days=1)))
    db.flush()
    proposal = _request(db, share=7_000, net=7_000)
    with pytest.raises(AppError) as error:
        _accept(db, proposal)
    assert error.value.error == "split_total_exceeds_parent"
    assert proposal.status == "pending"
    assert db.get(Debt, 1).row_version == 1


def test_a_decrease_can_resolve_old_overallocation_after_source_was_corrected(agreement_db):
    db = agreement_db
    db.get(Expense, 100).amount_cents = 1_000
    db.flush()
    _accept(db, _request(db, share=2_000, net=2_000))
    assert db.get(Debt, 1).row_version == 2
