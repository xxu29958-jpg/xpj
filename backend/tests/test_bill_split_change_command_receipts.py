"""Committed-but-unseen retries retain the original result and atomic facts."""

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import ApiIdempotencyKey, BillSplitAgreementChange, BillSplitChangeProposal, Debt, DebtAdjustment
from app.schemas._bill_split_change import BillSplitChangeAcceptRequest, BillSplitChangeCreateRequest
from app.services import bill_split_change_command_service as commands
from tests.bill_split_test_support import agreement_db as agreement_db
from tests.bill_split_test_support import record_agreement_payment as _paid


def create(db, split, *, key="propose", amount=2_000, actor="receiver"):
    return commands.create_bill_split_change_idempotently(db, tenant_id="split-receiver",
        actor_account_id=split[f"{actor}_id"], public_id=split["debt"], idempotency_key=key,
        payload=BillSplitChangeCreateRequest(new_share_amount_cents=amount, settlement_net_amount_cents=-amount,
            reason="Source refund", expected_row_version=1))


def accept(db, split, proposal):
    return commands.accept_bill_split_change_idempotently(db, tenant_id="owner",
        actor_account_id=split["sender_id"], public_id=split["debt"], proposal_public_id=proposal.public_id,
        payload=BillSplitChangeAcceptRequest(expected_row_version=1), idempotency_key="accept")


@pytest.mark.parametrize(("amount", "actor"), [(2_100, "receiver"), (2_000, "sender")])
def test_same_key_cannot_change_either_terms_or_actor(agreement_db, amount, actor):
    db, split = agreement_db
    create(db, split)
    with pytest.raises(AppError) as error:
        create(db, split, amount=amount, actor=actor)
    assert error.value.error == "idempotency_key_reused"
    assert len(list(db.scalars(select(BillSplitChangeProposal)))) == 1


def test_failure_after_fact_writes_rolls_back_both_legs_proposal_and_key(agreement_db, monkeypatch):
    db, split = agreement_db
    _paid(db, split, split["original_id"], 3_000)
    proposed = create(db, split)
    original_query = commands.get_bill_split_agreement

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("receipt serialization failed before commit")

    monkeypatch.setattr(commands, "get_bill_split_agreement", fail_receipt)
    with pytest.raises(RuntimeError):
        accept(db, split, proposed)
    assert db.get(Debt, split["original_id"]).row_version == 1
    assert db.scalar(select(Debt).where(Debt.source_type == "bill_split_return")) is None
    assert not list(db.scalars(select(BillSplitAgreementChange)))
    assert not list(db.scalars(select(DebtAdjustment)))
    assert db.scalar(select(BillSplitChangeProposal)).status == "pending"
    assert list(db.scalars(select(ApiIdempotencyKey.idempotency_key).where(ApiIdempotencyKey.idempotency_key.in_(("propose", "accept"))))) == ["propose"]
    monkeypatch.setattr(commands, "get_bill_split_agreement", original_query)
    assert accept(db, split, proposed).return_debt.remaining_amount_cents == 2_000


def test_a_nonparty_cannot_read_a_stored_receipt(agreement_db):
    db, split = agreement_db
    create(db, split)
    with pytest.raises(AppError) as error:
        create(db, split, actor="viewer")
    assert error.value.error == "split_change_party_only"
