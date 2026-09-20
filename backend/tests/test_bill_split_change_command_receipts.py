"""Committed-but-unseen retries retain the original result and atomic facts."""

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models import ApiIdempotencyKey, BillSplitAgreementChange, BillSplitChangeProposal, Debt, DebtAdjustment
from app.schemas._bill_split_change import BillSplitChangeAcceptRequest, BillSplitChangeCreateRequest
from app.services import bill_split_change_command_service as commands
from tests.test_bill_split_agreement_commands import _paid
from tests.test_bill_split_agreement_commands import agreement_db as agreement_db


def create(db, *, key="propose", amount=2_000, actor=1):
    return commands.create_bill_split_change_idempotently(db, tenant_id="receiver-private",
        actor_account_id=actor, public_id="original", idempotency_key=key,
        payload=BillSplitChangeCreateRequest(new_share_amount_cents=amount, settlement_net_amount_cents=-amount,
            reason="Source refund", expected_row_version=1))


def accept(db, proposal):
    return commands.accept_bill_split_change_idempotently(db, tenant_id="sender-private",
        actor_account_id=2, public_id="original", proposal_public_id=proposal.public_id,
        payload=BillSplitChangeAcceptRequest(expected_row_version=1), idempotency_key="accept")


def test_replay_returns_the_original_receipts_after_later_return_payment(agreement_db):
    db = agreement_db
    _paid(db, 1, 4_000)
    proposed = create(db)
    accepted = accept(db, proposed)
    returned = db.scalar(select(Debt).where(Debt.source_type == "bill_split_return"))
    _paid(db, returned.id, 800)
    returned.row_version += 1
    db.commit()
    assert create(db).model_dump(mode="json") == proposed.model_dump(mode="json")
    assert accept(db, proposed).model_dump(mode="json") == accepted.model_dump(mode="json")
    assert accepted.return_debt.remaining_amount_cents == 2_000
    assert len(list(db.scalars(select(BillSplitAgreementChange)))) == 1
    assert len(list(db.scalars(select(DebtAdjustment)))) == 0
    assert len(list(db.scalars(select(ApiIdempotencyKey)))) == 2


@pytest.mark.parametrize(("amount", "actor"), [(2_100, 1), (2_000, 2)])
def test_same_key_cannot_change_either_terms_or_actor(agreement_db, amount, actor):
    create(agreement_db)
    with pytest.raises(AppError) as error:
        create(agreement_db, amount=amount, actor=actor)
    assert error.value.error == "idempotency_key_reused"
    assert len(list(agreement_db.scalars(select(BillSplitChangeProposal)))) == 1


def test_failure_after_fact_writes_rolls_back_both_legs_proposal_and_key(agreement_db, monkeypatch):
    db = agreement_db
    _paid(db, 1, 3_000)
    proposed = create(db)
    original_query = commands.get_bill_split_agreement

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("receipt serialization failed before commit")

    monkeypatch.setattr(commands, "get_bill_split_agreement", fail_receipt)
    with pytest.raises(RuntimeError):
        accept(db, proposed)
    assert db.get(Debt, 1).row_version == 1
    assert db.scalar(select(Debt).where(Debt.source_type == "bill_split_return")) is None
    assert not list(db.scalars(select(BillSplitAgreementChange)))
    assert not list(db.scalars(select(DebtAdjustment)))
    assert db.scalar(select(BillSplitChangeProposal)).status == "pending"
    assert list(db.scalars(select(ApiIdempotencyKey.idempotency_key))) == ["propose"]
    monkeypatch.setattr(commands, "get_bill_split_agreement", original_query)
    assert accept(db, proposed).return_debt.remaining_amount_cents == 2_000


@pytest.mark.parametrize(("command", "actor", "status"), [
    (commands.reject_bill_split_change_idempotently, 2, "rejected"),
    (commands.withdraw_bill_split_change_idempotently, 1, "withdrawn"),
])
def test_terminal_action_replay_keeps_its_accepted_result(agreement_db, command, actor, status):
    db = agreement_db
    proposal = create(db)
    arguments = {"tenant_id": "receiver-private", "actor_account_id": actor, "public_id": "original",
        "proposal_public_id": proposal.public_id, "idempotency_key": "resolve"}
    result = command(db, **arguments)
    assert result.status == status
    assert command(db, **arguments).model_dump(mode="json") == result.model_dump(mode="json")
    assert db.get(Debt, 1).row_version == 1


def test_a_nonparty_cannot_read_a_stored_receipt(agreement_db):
    create(agreement_db)
    with pytest.raises(AppError) as error:
        create(agreement_db, actor=3)
    assert error.value.error == "split_change_party_only"
