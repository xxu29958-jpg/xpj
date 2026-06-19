"""ADR-0049 §4 bill-split → Debt linkage.

Accepting a ``BillSplitInvitation``, when the Debt rollout is enabled, also
creates the receiver's member ``Debt`` (``i_owe`` the sender) in the SAME
transaction as the receiver expense + the invited→accepted claim (§4: all
commit together or none). Defaults ON since ⑤b (ADR §0.1); the closed-period
(no-Debt) state is set up explicitly with the ``debt_rollout_off`` fixture. A
re-accept creates no second Debt; terminal statuses create none.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Account,
    BillSplitInvitation,
    Debt,
    Expense,
    Ledger,
    LedgerAuditLog,
    LedgerMember,
)
from app.services import bill_split_service as bsplit
from app.services.debt_service import create_bill_split_debt
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


@pytest.fixture
def debt_rollout_off(monkeypatch: pytest.MonkeyPatch):
    # ⑤b flipped the default ON, so the "accepted while OFF → no Debt" closed-period
    # state must now be set up explicitly. Mirrors ``debt_rollout_on``.
    monkeypatch.setenv("DEBT_ROLLOUT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_debt_rollout_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # ⑤b activation: the Debt rollout now defaults ON (forward-only, ADR §4 / §0.1).
    # With no env override the config default governs; flipping the default back to
    # False would turn this red.
    monkeypatch.delenv("DEBT_ROLLOUT_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().debt_rollout_enabled is True
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


def test_accept_without_rollout_creates_no_debt(
    client: TestClient, *, identity, debt_rollout_off
) -> None:
    # With the rollout explicitly OFF: accept still creates the receiver expense, no Debt.
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


def _invite_foreign_parent(
    client: TestClient, identity, receiver_account_id: int, *, share_cents: int = 3600
) -> str:
    # The sender's PARENT expense is foreign (USD); create_invitation copies the
    # parent's USD provenance onto the invitation. The invited SHARE is still a
    # home-currency amount (share_cents <= the parent's home amount_cents).
    with SessionLocal() as db:
        parent = Expense(
            tenant_id="owner",
            amount_cents=7200,  # ¥72.00 home == 10.00 USD @ 7.2
            home_currency_code="CNY",
            original_currency_code="USD",
            original_amount_minor=1000,  # 10.00 USD (the PARENT total, not a share)
            exchange_rate_to_cny=Decimal("7.20000000"),
            exchange_rate_date=date(2026, 5, 10),
            exchange_rate_source="manual",
            fx_status="ready",
            merchant="USD Diner",
            category="餐饮",
            source="iPhone截图",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(parent)
        db.commit()
        parent_id = parent.id
    resp = client.post(
        f"/api/expenses/{parent_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": share_cents},
    )
    assert resp.status_code in (200, 201), resp.json()
    return resp.json()["public_id"]


def test_foreign_parent_debt_stays_home_shape(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # Finding 1 / §4: even when the PARENT expense is foreign (USD), the
    # bill-split Debt is STRICT home-shape — the receiver owes the home-currency
    # share, not a USD principal. The invitation's frozen USD snapshot is the
    # PARENT total (original_amount_minor=1000 = 10 USD), so copying it onto a
    # share-sized principal would misstate the obligation as the full foreign
    # amount; it is deliberately NOT copied. The foreign origin stays auditable
    # via source_id -> the invitation, which keeps the snapshot.
    receiver_id = _seed_receiver()
    public_id = _invite_foreign_parent(client, identity, receiver_id, share_cents=3600)

    _accept(public_id, receiver_id)

    debts = _debts_for(public_id)
    assert len(debts) == 1
    debt = debts[0]
    assert debt.principal_amount_cents == 3600  # the home-currency share
    assert debt.home_currency_code == "CNY"  # frozen from the invitation snapshot
    # Strict home-shape: the parent's USD provenance is NOT copied onto the Debt.
    assert debt.original_currency_code is None
    assert debt.original_amount_minor is None
    assert debt.exchange_rate_to_cny is None
    assert debt.exchange_rate_date is None
    assert debt.exchange_rate_source is None
    # Foreign origin remains traceable via the linked invitation.
    assert debt.source_type == "bill_split"
    assert debt.source_id == public_id


def test_debt_failure_rolls_back_whole_accept(
    client: TestClient, *, identity, debt_rollout_on, monkeypatch: pytest.MonkeyPatch
) -> None:
    # §4 "all commit together or none": if the Debt insert fails AFTER the
    # invited->accepted claim, the receiver expense, the claim, and the audit row
    # must ALL roll back — nothing commits. real_db so the accept's rollback is a
    # real transaction rollback against a really-committed setup.
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id)

    def _boom(*args, **kwargs):
        raise RuntimeError("debt insert blew up")

    # Patch the name bound at the accept call site.
    monkeypatch.setattr(
        "app.services.bill_split_service._transitions.create_bill_split_debt", _boom
    )

    with pytest.raises(RuntimeError):
        _accept(public_id, receiver_id)

    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        assert inv.status == "invited"  # the invited->accepted claim rolled back
        assert inv.received_expense_id is None
        accepted_audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.invitation_public_id == public_id)
            .where(LedgerAuditLog.action == "bill_split_accepted")
        )
        assert accepted_audit is None  # the audit row rolled back
    assert _received_expense(public_id) is None  # the receiver expense rolled back
    assert _debts_for(public_id) == []  # no Debt


def test_two_sessions_accept_race_creates_single_debt(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # §4 / P3: two sessions hold the SAME pre-accept ('invited') read of one
    # invitation with the Debt rollout ON (the true interleaving, mirroring
    # test_bill_split_hardening.test_two_sessions_accept_race_creates_single_received_expense).
    # session_a accepts (commits the received expense + member Debt + the
    # invited→accepted claim); session_b THEN runs its STALE-'invited' accept —
    # its received-expense INSERT trips uq_expenses_split_origin_invitation →
    # IntegrityError → rollback → _resolve_lost_accept re-reads the now-'accepted'
    # invitation and returns session_a's expense WITHOUT reaching
    # create_bill_split_debt. That lost-claim branch is the dangerous path where a
    # second Debt could be attempted; uq_debts_source is its structural backstop.
    # Net: exactly ONE Debt and ONE received expense. real_db (the
    # ``test_two_sessions`` naming auto-marks it) so each session is a real
    # committed transaction; expire_on_commit=False keeps session_b's stale
    # 'invited' read, exercising the lost-claim recovery branch (not the settled
    # fast path).
    receiver_id = _seed_receiver(name="B-acc-race", ledger_id="receiver_accrace")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        # Both sessions take a pre-accept 'invited' read FIRST (the race setup).
        row_a = session_a.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        row_b = session_b.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert row_a is not None and row_b is not None
        assert row_a.status == "invited" and row_b.status == "invited"

        # Session A wins the claim and commits the Debt + received expense.
        bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_id,
            target_ledger_id="receiver_accrace",
        )
        # Session B's stale-'invited' accept loses the claim (its expense INSERT
        # trips the unique backstop) and must NOT create a second Debt.
        inv_b, expense_b = bsplit.accept_invitation(
            session_b,
            public_id=public_id,
            accepting_account_id=receiver_id,
            target_ledger_id="receiver_accrace",
        )
        assert inv_b.status == "accepted"
        assert expense_b.split_origin_invitation_id == public_id
    finally:
        session_a.close()
        session_b.close()

    # Exactly one Debt and one received expense — uq_debts_source +
    # uq_expenses_split_origin_invitation backstop the lost-claim branch.
    assert len(_debts_for(public_id)) == 1
    with SessionLocal() as db:
        received = list(
            db.scalars(select(Expense).where(Expense.split_origin_invitation_id == public_id))
        )
        assert len(received) == 1


def test_duplicate_bill_split_debt_source_is_rejected(client: TestClient, *, identity) -> None:
    # §10 hard constraint: ``uq_debts_source`` (source_type, source_id) is the
    # structural backstop that makes one accepted invitation map to at most one
    # bill-split Debt even if a path ever reached the insert twice. A second
    # create_bill_split_debt for the same invitation public_id raises an
    # IntegrityError (contained in a SAVEPOINT so the outer transaction survives).
    owner_id = _owner_account_id()
    receiver_id = _seed_receiver(name="B-dup", ledger_id="receiver_dup")
    source_invitation_public_id = str(uuid4())

    with SessionLocal() as db:
        create_bill_split_debt(
            db,
            ledger_id="receiver_dup",
            receiver_account_id=receiver_id,
            sender_account_id=owner_id,
            amount_cents=2500,
            home_currency_code="CNY",
            source_invitation_public_id=source_invitation_public_id,
            event_time=None,
        )
        with pytest.raises(IntegrityError), db.begin_nested():
            create_bill_split_debt(
                db,
                ledger_id="receiver_dup",
                receiver_account_id=receiver_id,
                sender_account_id=owner_id,
                amount_cents=2500,
                home_currency_code="CNY",
                source_invitation_public_id=source_invitation_public_id,
                event_time=None,
            )
