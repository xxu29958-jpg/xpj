"""Current PostgreSQL constraints; no translated tables or partial-index emulator."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import BillSplitAgreementChange, BillSplitChangeProposal, DebtAdjustment
from app.money_contract import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX
from app.services.currency_binding_service import resolve_write_capability
from tests.bill_split_test_support import accept_agreement_change as _accept
from tests.bill_split_test_support import agreement_db as agreement_db
from tests.bill_split_test_support import proposal_values
from tests.bill_split_test_support import request_agreement_change as _request
from tests.bill_split_test_support import split_http as split_http


@pytest.fixture
def storage(split_http):
    with SessionLocal() as db:
        resolve_write_capability(db)
        yield db, proposal_values(invitation_id=split_http["invitation_id"],
            original_debt_id=split_http["original_id"], proposed_by_account_id=split_http["receiver_id"])


def test_invalid_proposal_cannot_be_stored(storage):
    db, values = storage
    table = BillSplitChangeProposal.__table__
    # One real agreement setup, isolated failing inserts. Each constraint must
    # reject its own invalid input, not an unrelated uniqueness or FK failure.
    invalid = [
        ({"new_share_amount_cents": -1}, "ck_bscp_new_share_amount_cents"),
        ({"share_before_amount_cents": MONEY_MINOR_MAX + 1}, "ck_bscp_share_before_amount_cents"),
        ({"settlement_net_amount_cents": MONEY_MINOR_MAX + 1}, "ck_bscp_settlement_net_amount_cents"),
        ({"original_paid_amount_cents": MONEY_AGGREGATE_MAX + 1}, "ck_bscp_original_paid_amount_cents"),
        ({"return_forgiven_amount_cents": -1}, "ck_bscp_return_forgiven_amount_cents"),
        ({"settlement_before_net_amount_cents": -MONEY_AGGREGATE_MAX - 1}, "ck_bscp_settlement_before_net_amount_cents"),
        ({"status": "invented", "resolved_at": datetime.now(UTC)}, "ck_bscp_status"),
        ({"original_debt_row_version": 0}, "ck_bscp_original_version"),
        ({"return_debt_id": values["original_debt_id"]}, "ck_bscp_return_version"),
        ({"return_debt_row_version": 1}, "ck_bscp_return_version"),
        ({"return_debt_id": values["original_debt_id"], "return_debt_row_version": 1}, "ck_bscp_return_version"),
        ({"reason": ""}, "ck_bscp_reason"),
        ({"status": "accepted"}, "ck_bscp_resolution"),
        ({"invitation_id": -1}, "bill_split_change_proposals_invitation_id_fkey"),
    ]
    for changes, constraint in invalid:
        with pytest.raises(IntegrityError, match=constraint), db.begin_nested():
            db.execute(insert(table).values(**{**values, **changes}))
    first = db.execute(insert(table).values(**values)).inserted_primary_key[0]
    with pytest.raises(IntegrityError, match="uq_bscp_one_pending"), db.begin_nested():
        db.execute(insert(table).values(**{**values, "public_id": str(uuid4())}))
    db.execute(table.update().where(table.c.id == first).values(
        status="withdrawn", resolved_at=datetime.now(UTC), resolved_by_account_id=values["proposed_by_account_id"]))
    db.execute(insert(table).values(**{**values, "public_id": str(uuid4())}))
    assert len(db.execute(select(table)).all()) == 2


def test_zero_share_signed_settlement_and_large_fold_snapshots_are_valid(storage):
    db, values = storage
    db.execute(insert(BillSplitChangeProposal).values(**{**values,
        "new_share_amount_cents": 0, "settlement_net_amount_cents": -MONEY_MINOR_MAX,
        "original_paid_amount_cents": MONEY_AGGREGATE_MAX,
        "settlement_before_net_amount_cents": -MONEY_AGGREGATE_MAX}))


def test_acceptance_is_unique_and_retains_both_adjustment_links(agreement_db):
    db, split = agreement_db
    _accept(db, split, _request(db, split, share=2_000, net=-2_000))
    change = _accept(db, split, _request(db, split, share=3_500, net=300))
    original_adjustment = db.get(DebtAdjustment, change.original_adjustment_id)
    return_adjustment = db.get(DebtAdjustment, change.return_adjustment_id)
    assert (original_adjustment.debt_id, original_adjustment.amount_cents) == (split["original_id"], 300)
    assert (return_adjustment.debt_id, return_adjustment.amount_cents) == (change.return_debt_id, -2_000)
    table = BillSplitAgreementChange.__table__
    duplicate = {column.name: getattr(change, column.name) for column in table.columns if column.name != "id"}
    duplicate["public_id"] = str(uuid4())
    with pytest.raises(IntegrityError, match="bill_split_agreement_changes_proposal_id_key"), db.begin_nested():
        db.execute(insert(table).values(**duplicate))
