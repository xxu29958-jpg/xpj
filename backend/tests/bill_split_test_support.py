"""Shared real database and HTTP setup for bilateral bill-split consumers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, AuthToken, BillSplitInvitation, Debt, Device, Expense, Ledger, LedgerMember, Repayment
from app.schemas._bill_split_change import BillSplitChangeAcceptRequest, BillSplitChangeCreateRequest
from app.services.bill_split_service._agreement_commands import accept_bill_split_change, create_bill_split_change
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.identity_service import hash_secret, new_session_token
from app.services.ledger_calendar_service import adopt_ledger_calendar
from app.services.time_service import now_utc
from tests._runtime_protocol import current_protocol_headers, negotiated_headers
from tests.debt_proposal_helpers import _idem, _member_headers, _propose


def _split_headers(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    return negotiated_headers(client, {"Idempotency-Key": str(uuid4()), **headers})


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_receiver(
    name: str = "B", ledger_id: str = "receiver_b", *, ledger_name: str | None = None,
) -> int:
    """Create a second account + their own personal ledger where they are owner."""
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        ledger = Ledger(ledger_id=ledger_id, name=ledger_name or f"{name} 的账本", owner_account_id=account.id)
        db.add(ledger)
        db.flush()
        adopt_ledger_calendar(db, ledger_id=ledger_id, timezone_name="Asia/Shanghai", actor_account_id=account.id)
        member = LedgerMember(
            ledger_id=ledger_id,
            account_id=account.id,
            role="owner",
        )
        db.add(member)
        db.commit()
        return account.id


def _make_expense_for_owner(*, amount_cents: int = 5000, merchant: str = "Pizza Place") -> int:
    """Insert an expense into owner ledger directly (bypasses upload flow)."""
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=amount_cents,
            merchant=merchant,
            category="餐饮",
            source="iPhone截图",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        refresh_legacy_expense_time(db, expense)
        db.add(expense)
        db.commit()
        return expense.id


def _bearer_for_account_ledger(account_id: int, ledger_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        device = Device(
            account_id=account_id,
            device_name="pytest-bill-split",
            platform="android",
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account_id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        db.commit()
    return current_protocol_headers({"Authorization": f"Bearer {token}"})


def _create_invited_split(
    client: TestClient,
    identity,
    receiver_account_id: int,
    *,
    amount_cents: int = 2500,
) -> str:
    """Owner sends a split invite to ``receiver_account_id``; return its public_id."""
    expense_id = _make_expense_for_owner()
    resp = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=_split_headers(client, identity.app_headers),
        json={"expected_row_version": 1, "receiver_account_id": receiver_account_id, "amount_cents": amount_cents},
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["public_id"]


def _debts_for(public_id: str) -> list[Debt]:
    with SessionLocal() as db:
        return list(db.scalars(select(Debt).where(Debt.source_id == public_id)))


def _seed_web_receiver(ledger_id: str = "receiver_web", display: str = "B-web") -> tuple[int, str]:
    return _seed_receiver(display, ledger_id, ledger_name=f"{display} 账本"), ledger_id


def _make_web_expense(amount_cents: int = 4000) -> int:
    return _make_expense_for_owner(amount_cents=amount_cents, merchant="Pizza")


def accepted_split(client, identity):
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
        original = db.scalar(select(Debt).where(Debt.source_type == "bill_split", Debt.source_id == invitation_id))
        original_id, public_id = original.id, original.public_id
        invitation = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == invitation_id))
        invitation_row_id = invitation.id
    with SessionLocal() as db:
        sender_id = db.scalar(select(AuthToken.account_id).where(
            AuthToken.token_hash == hash_secret(identity.app_token)))
    return {"sender": identity.app_headers, "sender_id": sender_id,
        "receiver": receiver, "receiver_id": receiver_id, "debt": public_id,
        "source": source_id, "invitation": invitation_id,
        "original_id": original_id, "invitation_id": invitation_row_id}


def split_view(client, headers, public_id):
    response = client.get(f"/api/debts/{public_id}/split-agreement", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()


def split_versions(view):
    returned = view["return_debt"]
    return {"expected_row_version": view["original_debt"]["row_version"],
        "expected_return_row_version": returned["row_version"] if returned else None}


def change_split_http(client, split, *, share, net):
    view = split_view(client, split["receiver"], split["debt"])
    response = client.post(f"/api/debts/{split['debt']}/split-change-proposals", headers=_idem(split["receiver"]),
        json={**split_versions(view), "new_share_amount_cents": share, "settlement_net_amount_cents": net,
            "reason": "Review source refund"})
    assert response.status_code == 201, response.json()
    return response.json(), view


def accept_split_http(client, split, proposal, basis, *, headers=None):
    return client.post(f"/api/debts/{split['debt']}/split-change-proposals/{proposal['public_id']}/accept",
        headers=headers or _idem(split["sender"]), json=split_versions(basis))


def pay_member_http(client, debtor, creditor, public_id, amount):
    proposal = _propose(client, debtor, public_id, proposed_amount_cents=amount)
    assert proposal.status_code == 201, proposal.json()
    debt = client.get(f"/api/debts/{public_id}", headers=creditor).json()
    confirmed = client.post(f"/api/debts/{public_id}/repayment-proposals/{proposal.json()['public_id']}/confirm",
        headers=_idem(creditor), json={"expected_row_version": debt["row_version"]})
    assert confirmed.status_code == 201, confirmed.json()
    return confirmed.json()


@pytest.fixture
def split_http(client, identity):
    return accepted_split(client, identity)


WHEN = datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest.fixture
def agreement_db(client, identity):
    split = accepted_split(client, identity)
    with SessionLocal() as db:
        resolve_write_capability(db)
        viewer = Account(display_name="Ledger viewer")
        db.add(viewer)
        db.flush()
        db.add(LedgerMember(ledger_id="split-receiver", account_id=viewer.id, role="viewer"))
        split["viewer_id"] = viewer.id
        db.commit()
        yield db, split


def request_agreement_change(db, split, *, share, net, actor="receiver", supersedes=None):
    original = db.get(Debt, split["original_id"])
    returned = db.scalar(select(Debt).where(Debt.source_type == "bill_split_return", Debt.source_id == split["invitation"]))
    return create_bill_split_change(db, tenant_id="split-receiver", actor_account_id=split[f"{actor}_id"],
        public_id=split["debt"], payload=BillSplitChangeCreateRequest(new_share_amount_cents=share,
            settlement_net_amount_cents=net, reason="Both review the source refund",
            expected_row_version=original.row_version,
            expected_return_row_version=returned.row_version if returned else None,
            supersedes_proposal_public_id=supersedes))


def accept_agreement_change(db, split, proposal, *, actor="sender"):
    return accept_bill_split_change(db, tenant_id="owner" if actor == "sender" else "split-receiver",
        actor_account_id=split[f"{actor}_id"], public_id=split["debt"], proposal_public_id=proposal.public_id,
        payload=BillSplitChangeAcceptRequest(expected_row_version=proposal.original_debt_row_version,
            expected_return_row_version=proposal.return_debt_row_version), idempotency_key=f"accept-{proposal.public_id}")


def record_agreement_payment(db, split, debt_id, amount):
    resolve_write_capability(db)
    db.add(Repayment(debt_id=debt_id, amount_cents=amount, actor_account_id=split["receiver_id"],
        idempotency_key=f"paid-{debt_id}", paid_at=WHEN, created_at=WHEN))
    db.flush()


def proposal_values(**changes):
    now = datetime(2026, 9, 20, tzinfo=UTC)
    return {
        "public_id": str(uuid4()), "invitation_id": 1, "proposed_by_account_id": 1,
        "original_debt_id": 1, "original_debt_row_version": 1,
        "share_before_amount_cents": 40, "new_share_amount_cents": 20,
        "settlement_net_amount_cents": -20, "settlement_before_net_amount_cents": 0,
        "original_paid_amount_cents": 40, "return_paid_amount_cents": 0,
        "original_forgiven_amount_cents": 0, "return_forgiven_amount_cents": 0,
        "reason": "Review source refund", "status": "pending", "created_at": now,
        "expires_at": now + timedelta(days=7), **changes,
    }
