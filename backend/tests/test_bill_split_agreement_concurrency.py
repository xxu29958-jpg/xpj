"""Real independent PG connections fence both settlement legs and source capacity."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, BillSplitAgreementChange, BillSplitChangeProposal, Debt, Expense
from app.schemas._bill_split_change import BillSplitChangeAcceptRequest
from app.services.bill_split_change_command_service import accept_bill_split_change_idempotently
from tests.test_bill_split_agreement_http import _accept, _change, _pay, _versions
from tests.test_bill_split_agreement_http import split_http as split_http

pytestmark = pytest.mark.real_db


@pytest.mark.parametrize("held_resource", ["returned_debt", "source_expense"])
def test_accept_waits_for_return_cash_and_source_allocation_writers(client, split_http, held_resource):
    split = split_http
    _pay(client, split["receiver"], split["sender"], split["debt"], 4_000)
    proposal, basis = _change(client, split, share=2_000, net=-2_000)
    accepted = _accept(client, split, proposal, basis)
    assert accepted.status_code == 200, accepted.json()
    proposed, next_basis = _change(client, split, share=2_500, net=-1_500)
    key = str(uuid4())
    with SessionLocal() as holder:
        original = holder.scalar(select(Debt).where(Debt.public_id == split["debt"]))
        target = (select(Debt).where(Debt.public_id == next_basis["return_debt"]["public_id"])
            if held_resource == "returned_debt" else select(Expense).where(Expense.id == split["source"]))
        holder.scalar(target.with_for_update())
        with SessionLocal() as blocked, pytest.raises(OperationalError):
            blocked.execute(text("SET LOCAL lock_timeout = '500ms'"))
            accept_bill_split_change_idempotently(blocked, tenant_id="owner", actor_account_id=original.counterparty_account_id,
                public_id=split["debt"], proposal_public_id=proposed["public_id"], idempotency_key=key,
                payload=BillSplitChangeAcceptRequest(**_versions(next_basis)))
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey.id).where(ApiIdempotencyKey.idempotency_key == key)) is None
        assert db.scalar(select(BillSplitChangeProposal.status).where(
            BillSplitChangeProposal.public_id == proposed["public_id"])) == "pending"
        assert len(list(db.scalars(select(BillSplitAgreementChange)))) == 1
    retried = _accept(client, split, proposed, next_basis, headers={**split["sender"], "Idempotency-Key": key})
    assert retried.status_code == 200, retried.json()
    assert retried.json()["settlement_net_amount_cents"] == -1_500
