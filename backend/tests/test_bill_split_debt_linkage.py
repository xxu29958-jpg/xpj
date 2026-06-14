"""ADR-0049 §4 bill-split → Debt linkage.

Accepting a ``BillSplitInvitation``, when the Debt rollout is enabled, also
creates the receiver's member ``Debt`` (``i_owe`` the sender) in the SAME
transaction as the receiver expense + the invited→accepted claim (§4: all
commit together or none). Gated OFF by default (ADR §0.1 runtime subset). A
re-accept creates no second Debt; terminal statuses create none.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Account, Debt, Expense, Ledger, LedgerMember
from app.services import bill_split_service as bsplit
from app.services.time_service import now_utc


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_receiver(name: str = "B", ledger_id: str = "receiver_b") -> int:
    """A second account + their own personal ledger where they are owner."""
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id=ledger_id, name=f"{name} 的账本", owner_account_id=account.id))
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="owner"))
        db.commit()
        return account.id


def _make_expense_for_owner(*, amount_cents: int = 5000, merchant: str = "Pizza Place") -> int:
    with SessionLocal() as db:
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
        db.add(expense)
        db.commit()
        return expense.id


def _invite(client: TestClient, identity, receiver_account_id: int, *, amount_cents: int = 2500) -> str:
    expense_id = _make_expense_for_owner()
    resp = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": amount_cents},
    )
    assert resp.status_code in (200, 201), resp.json()
    return resp.json()["public_id"]


def _accept(public_id: str, receiver_account_id: int, target_ledger_id: str = "receiver_b") -> None:
    # Accept directly via service: the test fixture has only the owner's auth
    # token, so the receiver side is driven through the service (mirrors
    # test_bill_split.py).
    with SessionLocal() as db:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id=target_ledger_id,
        )


def _debts_for(public_id: str) -> list[Debt]:
    with SessionLocal() as db:
        return list(db.scalars(select(Debt).where(Debt.source_id == public_id)))


def _received_expense(public_id: str) -> Expense | None:
    with SessionLocal() as db:
        return db.scalar(select(Expense).where(Expense.split_origin_invitation_id == public_id))


@pytest.fixture
def debt_rollout_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEBT_ROLLOUT_ENABLED", "true")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_accept_with_rollout_creates_member_debt(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # §4: accepting creates the receiver's member Debt (i_owe the sender) for the
    # agreed home-currency share, in the same transaction as the receiver expense.
    owner_id = _owner_account_id()
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)

    _accept(public_id, receiver_id)

    debts = _debts_for(public_id)
    assert len(debts) == 1
    debt = debts[0]
    assert debt.tenant_id == "receiver_b"  # the receiver's chosen target ledger
    assert debt.owner_account_id == receiver_id
    assert debt.created_by_account_id == receiver_id
    assert debt.direction == "i_owe"
    assert debt.counterparty_type == "member"
    assert debt.counterparty_account_id == owner_id  # the sender
    assert debt.counterparty_label is None
    assert debt.principal_amount_cents == 2500  # the home-currency share, not 5000
    assert debt.home_currency_code == "CNY"
    assert debt.original_currency_code is None  # home-currency share → no provenance
    assert debt.original_amount_minor is None
    assert debt.source_type == "bill_split"
    assert debt.source_id == public_id
    assert debt.status == "open"
    assert debt.row_version == 1  # brand-new Debt is not hand-bumped
    # Same transaction: the receiver expense committed too.
    received = _received_expense(public_id)
    assert received is not None
    assert received.tenant_id == "receiver_b"


def test_accept_without_rollout_creates_no_debt(client: TestClient, *, identity) -> None:
    # Default (rollout off): accept still creates the receiver expense, no Debt.
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id)

    _accept(public_id, receiver_id)

    assert _debts_for(public_id) == []
    assert _received_expense(public_id) is not None


def test_reaccept_does_not_create_second_debt(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # §4: a re-accept returns the existing accepted result and MUST NOT create
    # another Debt (the fast path returns before the insert; uq_debts_source
    # backstops).
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id)

    _accept(public_id, receiver_id)
    _accept(public_id, receiver_id)  # idempotent re-accept

    assert len(_debts_for(public_id)) == 1


def test_reject_creates_no_debt(client: TestClient, *, identity, debt_rollout_on) -> None:
    # Rejected invitations create no Debt (§4).
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id)

    with SessionLocal() as db:
        bsplit.reject_invitation(db, public_id=public_id, rejecting_account_id=receiver_id)

    assert _debts_for(public_id) == []
