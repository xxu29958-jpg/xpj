"""Actual PostgreSQL/HTTP journeys, including the existing repayment workflow."""

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthToken, BillSplitAgreementChange, BillSplitInvitation, Debt, Device, Expense
from app.services.identity_service import hash_secret, new_session_token
from tests.debt_proposal_helpers import _idem, _member_headers, _propose
from tests.test_bill_split import _make_expense_for_owner, _seed_receiver


@pytest.fixture
def split_http(client, identity):
    receiver_id = _seed_receiver("Receiver", "split-receiver")
    with SessionLocal() as db:
        device = Device(account_id=receiver_id, device_name="Split test", platform="android")
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(AuthToken(token_hash=hash_secret(token), account_id=receiver_id, device_id=device.id,
            ledger_id="split-receiver", scope="app"))
        db.commit()
    receiver = _member_headers(token)
    source_id = _make_expense_for_owner(amount_cents=10_000)
    invited = client.post(f"/api/expenses/{source_id}/split-invite", headers=_idem(identity.app_headers),
        json={"expected_row_version": 1, "receiver_account_id": receiver_id, "amount_cents": 4_000})
    assert invited.status_code == 200, invited.json()
    invitation_id = invited.json()["public_id"]
    accepted = client.post(f"/api/bill-splits/{invitation_id}/accept", headers=receiver,
        json={"target_ledger_id": "split-receiver"})
    assert accepted.status_code == 200, accepted.json()
    with SessionLocal() as db:
        public_id = db.scalar(select(Debt.public_id).where(Debt.source_type == "bill_split", Debt.source_id == invitation_id))
    return {"sender": identity.app_headers, "receiver": receiver, "debt": public_id,
        "source": source_id, "invitation": invitation_id}


def _view(client, headers, public_id):
    response = client.get(f"/api/debts/{public_id}/split-agreement", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()


def _versions(view):
    returned = view["return_debt"]
    return {"expected_row_version": view["original_debt"]["row_version"],
        "expected_return_row_version": returned["row_version"] if returned else None}


def _change(client, split, *, share, net):
    view = _view(client, split["receiver"], split["debt"])
    response = client.post(f"/api/debts/{split['debt']}/split-change-proposals", headers=_idem(split["receiver"]),
        json={**_versions(view), "new_share_amount_cents": share, "settlement_net_amount_cents": net,
            "reason": "Review source refund"})
    assert response.status_code == 201, response.json()
    return response.json(), view


def _accept(client, split, proposal, basis, *, headers=None):
    return client.post(f"/api/debts/{split['debt']}/split-change-proposals/{proposal['public_id']}/accept",
        headers=headers or _idem(split["sender"]), json=_versions(basis))


def _pay(client, debtor, creditor, public_id, amount):
    proposal = _propose(client, debtor, public_id, proposed_amount_cents=amount)
    assert proposal.status_code == 201, proposal.json()
    debt = client.get(f"/api/debts/{public_id}", headers=creditor).json()
    confirmed = client.post(f"/api/debts/{public_id}/repayment-proposals/{proposal.json()['public_id']}/confirm",
        headers=_idem(creditor), json={"expected_row_version": debt["row_version"]})
    assert confirmed.status_code == 201, confirmed.json()
    return confirmed.json()


def test_paid_share_refund_partial_return_and_changed_mind_preserve_actual_cash(client, split_http):
    split = split_http
    _pay(client, split["receiver"], split["sender"], split["debt"], 4_000)
    proposal, basis = _change(client, split, share=2_000, net=-2_000)
    headers = _idem(split["sender"])
    accepted = _accept(client, split, proposal, basis, headers=headers)
    assert accepted.status_code == 200, accepted.json()
    original_receipt = accepted.json()
    returned_id = original_receipt["return_debt"]["public_id"]
    payables = client.get("/api/debts?lens=payables", headers=split["sender"]).json()["items"]
    assert returned_id in [debt["public_id"] for debt in payables]
    _pay(client, split["sender"], split["receiver"], returned_id, 800)
    replay = _accept(client, split, proposal, basis, headers=headers)
    assert replay.status_code == 200, replay.json()
    assert replay.json() == original_receipt
    next_proposal, next_basis = _change(client, split, share=3_000, net=-200)
    next_result = _accept(client, split, next_proposal, next_basis)
    assert next_result.status_code == 200, next_result.json()
    assert next_result.json()["return_debt"]["public_id"] == returned_id
    last_proposal, last_basis = _change(client, split, share=3_500, net=300)
    last = _accept(client, split, last_proposal, last_basis)
    assert last.status_code == 200, last.json()
    assert last.json()["original_debt"]["remaining_amount_cents"] == 300
    assert last.json()["return_debt"]["remaining_amount_cents"] == 0
    assert last.json()["original_paid_amount_cents"] == 4_000
    assert last.json()["return_paid_amount_cents"] == 800
    assert last.json()["original_debt"]["ledger_id"] is None
    with SessionLocal() as db:
        invitation = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == split["invitation"]))
        assert db.get(Expense, split["source"]).amount_cents == 10_000
        assert db.get(Expense, invitation.received_expense_id).amount_cents == 4_000
        assert len(list(db.scalars(select(BillSplitAgreementChange)))) == 3


def test_return_payment_pending_blocks_accept_and_confirming_it_invalidates_old_basis(client, split_http):
    split = split_http
    _pay(client, split["receiver"], split["sender"], split["debt"], 4_000)
    proposal, basis = _change(client, split, share=2_000, net=-2_000)
    result = _accept(client, split, proposal, basis)
    assert result.status_code == 200, result.json()
    returned = result.json()["return_debt"]
    next_proposal, next_basis = _change(client, split, share=3_000, net=-1_000)
    payment = _propose(client, split["sender"], returned["public_id"], proposed_amount_cents=800)
    assert payment.status_code == 201, payment.json()
    refused = _accept(client, split, next_proposal, next_basis)
    assert refused.status_code == 409
    assert refused.json()["error"] == "split_change_repayment_pending"
    confirmed = client.post(f"/api/debts/{returned['public_id']}/repayment-proposals/{payment.json()['public_id']}/confirm",
        headers=_idem(split["receiver"]), json={"expected_row_version": returned["row_version"]})
    assert confirmed.status_code == 201, confirmed.json()
    stale = _accept(client, split, next_proposal, next_basis)
    assert stale.status_code == 409
    assert stale.json()["error"] == "state_conflict"
    view = _view(client, split["receiver"], split["debt"])
    assert view["agreed_share_amount_cents"] == 2_000
    assert view["settlement_net_amount_cents"] == -1_200
    assert view["pending_proposal"]["public_id"] == next_proposal["public_id"]
