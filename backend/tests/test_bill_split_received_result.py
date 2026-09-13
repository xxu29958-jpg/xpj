"""A receiver can recover its own accepted fact without exposing either party's private ledger."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import BillSplitInvitation, Expense, Ledger, LedgerMember
from app.services.time_service import now_utc
from tests._runtime_protocol import negotiated_headers
from tests.test_bill_split import _seed_receiver
from tests.test_bill_split_party_authorization import _create_invited_split
from tests.test_bill_split_security_regressions import _bearer_for_account_ledger


def _accepted_result(client: TestClient, identity) -> tuple[str, int, dict[str, str], dict]:
    receiver = _seed_receiver(name="Receiver result", ledger_id="receiver_result")
    public_id = _create_invited_split(client, identity, receiver_account_id=receiver)
    with SessionLocal() as db:
        db.add(LedgerMember(ledger_id="owner", account_id=receiver, role="viewer"))
        db.commit()
    # The current ledger is read-only; the chosen destination belongs to the receiver.
    headers = negotiated_headers(client, _bearer_for_account_ledger(receiver, "owner"))
    response = client.post(f"/api/bill-splits/{public_id}/accept", headers=headers,
                           json={"target_ledger_id": "receiver_result"})
    assert response.status_code == 200, response.json()
    return public_id, receiver, headers, response.json()


def test_accepted_result_survives_response_loss_and_reentry(client: TestClient, *, identity) -> None:
    public_id, _receiver, headers, accepted = _accepted_result(client, identity)
    with SessionLocal() as db:
        invitation = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id))
        expected = {"expense_id": invitation.received_expense_id,
                    "ledger_id": "receiver_result", "ledger_name": "Receiver result 的账本"}
    assert accepted.get("received_bill") == expected

    replay = client.post(f"/api/bill-splits/{public_id}/accept", headers=headers,
                         json={"target_ledger_id": "receiver_result"})
    assert replay.status_code == 200, replay.json()
    assert replay.json()["received_bill"] == expected
    inbox = client.get("/api/bill-splits/inbox", headers=headers)
    assert inbox.status_code == 200, inbox.json()
    row = next(item for item in inbox.json()["items"] if item["public_id"] == public_id)
    assert row["received_bill"] == expected
    assert "sender_expense_id" not in row and "sender_ledger_id" not in row
    sent = client.get("/api/bill-splits/sent", headers=identity.app_headers).json()["items"]
    assert all("received_bill" not in item and "receiver_ledger_id" not in item for item in sent)
    with SessionLocal() as db:
        received = db.scalars(select(Expense).where(Expense.tenant_id == "receiver_result")).all()
        assert [expense.id for expense in received] == [expected["expense_id"]]


@pytest.mark.parametrize("access", ["viewer", "disabled", "archived"])
def test_result_reference_obeys_current_target_access(client: TestClient, *, identity, access: str) -> None:
    public_id, receiver, headers, _accepted = _accepted_result(client, identity)
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "receiver_result",
                                                     LedgerMember.account_id == receiver))
        if access == "viewer":
            member.role = "viewer"
        elif access == "disabled":
            member.disabled_at = now_utc()
        else:
            db.scalar(select(Ledger).where(Ledger.ledger_id == "receiver_result")).archived_at = now_utc()
        db.commit()
    response = client.get("/api/bill-splits/inbox", headers=headers)
    assert response.status_code == 200, response.json()
    row = next(item for item in response.json()["items"] if item["public_id"] == public_id)
    assert row["status"] == "accepted"
    if access == "viewer":
        assert row.get("received_bill", {}).get("ledger_id") == "receiver_result"
    else:
        assert row.get("received_bill") is None
