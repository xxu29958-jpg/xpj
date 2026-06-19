"""ADR-0049 §4 / P3b: backfill the member Debt for bill splits accepted while the
Debt rollout was OFF, and the startup self-heal that gates it on the flag.

Splits accepted during the closed-rollout period have no member Debt. ``backfill_
bill_split_debts`` creates exactly the Debt the accept transaction would have (the
same ``create_bill_split_debt`` entry → byte-identical shape). ``reconcile_bill_
split_debts_if_enabled`` is the startup self-heal: it runs the backfill ONLY when the
rollout is ON, so flipping the flag (⑤b) catches up history; while OFF it is a no-op
(an accepted split legitimately has no Debt then — fabricating one would be wrong).

Mirrors ``test_bill_split_debt_linkage.py``'s form (own helpers, the owner invites a
seeded receiver, accept driven through the service).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Account, BillSplitInvitation, Debt, Expense, Ledger, LedgerMember
from app.services import bill_split_service as bsplit
from app.services.bill_split_service import (
    backfill_bill_split_debts,
    reconcile_bill_split_debts_if_enabled,
)
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
    # Accept via the service (the test fixture holds only the owner's token), the
    # same as test_bill_split_debt_linkage. Whether a Debt is created inline depends
    # on the current DEBT_ROLLOUT_ENABLED setting at accept time.
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


def _run_backfill() -> int:
    with SessionLocal() as db:
        return backfill_bill_split_debts(db)


def _invite_foreign_parent(
    client: TestClient, identity, receiver_account_id: int, *, share_cents: int = 3600
) -> str:
    # The sender's PARENT expense is foreign (USD); the invited SHARE is still a
    # home-currency amount (mirrors test_bill_split_debt_linkage._invite_foreign_parent).
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
    # ⑤b flipped the default ON. The backfill tests need the closed-period state (a
    # split accepted while OFF, so no inline Debt) set up explicitly. Mirrors
    # ``debt_rollout_on``.
    monkeypatch.setenv("DEBT_ROLLOUT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_backfill_creates_missing_member_debt(
    client: TestClient, *, identity, debt_rollout_off
) -> None:
    # A split accepted while the rollout was OFF has no Debt; backfill creates one
    # with the exact shape an inline-at-accept Debt would have (mirrors
    # test_bill_split_debt_linkage.test_accept_with_rollout_creates_member_debt).
    owner_id = _owner_account_id()
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept(public_id, receiver_id)  # rollout OFF → accepted, no Debt
    assert _debts_for(public_id) == []

    assert _run_backfill() == 1

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


def test_backfill_skips_invitation_that_already_has_debt(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # Accepted with the rollout ON → the Debt already exists inline. Backfill finds
    # nothing missing and creates no duplicate.
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept(public_id, receiver_id)
    assert len(_debts_for(public_id)) == 1

    assert _run_backfill() == 0
    assert len(_debts_for(public_id)) == 1


def test_backfill_is_idempotent_on_rerun(
    client: TestClient, *, identity, debt_rollout_off
) -> None:
    # First run creates the missing Debt; the second is a clean no-op (the
    # missing-Debt query is now empty).
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept(public_id, receiver_id)  # rollout OFF → no Debt

    assert _run_backfill() == 1
    assert len(_debts_for(public_id)) == 1
    assert _run_backfill() == 0
    assert len(_debts_for(public_id)) == 1


def test_backfill_ignores_non_accepted_invitations(client: TestClient, *, identity) -> None:
    # Only 'accepted' invitations are backfillable: an 'invited' (never accepted) and
    # a 'rejected' invitation must create no Debt. Each invite uses a distinct parent
    # expense (the pending-invite unique is per sender_expense_id).
    receiver_id = _seed_receiver()
    invited_pid = _invite(client, identity, receiver_id, amount_cents=2500)
    rejected_pid = _invite(client, identity, receiver_id, amount_cents=2500)
    with SessionLocal() as db:
        bsplit.reject_invitation(db, public_id=rejected_pid, rejecting_account_id=receiver_id)

    assert _run_backfill() == 0
    assert _debts_for(invited_pid) == []
    assert _debts_for(rejected_pid) == []


def test_reconcile_is_noop_when_rollout_off(
    client: TestClient, *, identity, debt_rollout_off
) -> None:
    # The safety invariant: a split accepted in the closed period legitimately has no
    # Debt, so the startup reconcile must NOT fabricate one while the rollout is OFF.
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept(public_id, receiver_id)  # rollout OFF → no Debt
    assert _debts_for(public_id) == []

    assert reconcile_bill_split_debts_if_enabled() == 0
    assert _debts_for(public_id) == []


def test_reconcile_backfills_when_rollout_on(
    client: TestClient, *, identity, debt_rollout_off, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The flip-the-flag path: a split accepted while OFF gets its Debt backfilled the
    # moment the reconcile runs with the rollout ON (⑤b). The ``debt_rollout_off``
    # fixture seeds the closed-period accept (no inline Debt); this test then flips
    # the same monkeypatch'd env ON to exercise the startup reconcile.
    owner_id = _owner_account_id()
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept(public_id, receiver_id)  # accepted while OFF → no Debt yet
    assert _debts_for(public_id) == []

    monkeypatch.setenv("DEBT_ROLLOUT_ENABLED", "true")
    get_settings.cache_clear()
    try:
        assert reconcile_bill_split_debts_if_enabled() == 1
    finally:
        get_settings.cache_clear()

    debts = _debts_for(public_id)
    assert len(debts) == 1
    debt = debts[0]
    assert debt.tenant_id == "receiver_b"
    assert debt.owner_account_id == receiver_id
    assert debt.counterparty_account_id == owner_id
    assert debt.direction == "i_owe"
    assert debt.counterparty_type == "member"
    assert debt.source_type == "bill_split"
    assert debt.source_id == public_id
    assert debt.principal_amount_cents == 2500
    assert debt.status == "open"
    assert debt.row_version == 1


def test_backfill_status_filter_excludes_non_accepted_with_bound_ledger(
    client: TestClient, *, identity, debt_rollout_off
) -> None:
    # The status=='accepted' filter is the operative gate, INDEPENDENT of the
    # receiver_ledger_id guard: an invitation that reached 'accepted' (so its ledger
    # IS bound) but whose status was later moved away from 'accepted' must not be
    # backfilled. Removing the status filter would NOT be caught by the
    # receiver_ledger_id guard here (the ledger is non-null), so this pins the filter.
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept(public_id, receiver_id)  # OFF → accepted, ledger bound, no Debt
    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None and inv.receiver_ledger_id is not None  # ledger bound
        inv.status = "cancelled"  # non-accepted status while keeping the bound ledger
        db.commit()

    assert _run_backfill() == 0
    assert _debts_for(public_id) == []


def test_backfill_skips_accepted_with_null_ledger(
    client: TestClient, *, identity, debt_rollout_off
) -> None:
    # Defensive guard: an 'accepted' row with a NULL receiver_ledger_id (structurally
    # impossible via the atomic accept claim, but guarded against) must be SKIPPED, not
    # turned into a tenant-less Debt. Pins the `if inv.receiver_ledger_id is None` branch.
    receiver_id = _seed_receiver()
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept(public_id, receiver_id)  # OFF → accepted, ledger bound, no Debt
    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        # Null the whole receiver binding (keep status 'accepted') — the malformed row.
        inv.receiver_ledger_id = None
        inv.receiver_member_id = None
        inv.received_expense_id = None
        db.commit()

    assert _run_backfill() == 0
    assert _debts_for(public_id) == []


def test_backfill_foreign_parent_debt_stays_home_shape(
    client: TestClient, *, identity, debt_rollout_off
) -> None:
    # Strict home-shape on the BACKFILL path: even when the PARENT expense is foreign
    # (USD), the backfilled Debt owes the home-currency share with NO copied USD
    # provenance — identical to the inline accept path (mirrors
    # test_bill_split_debt_linkage.test_foreign_parent_debt_stays_home_shape, pinned
    # here against drift in the backfill entry specifically).
    receiver_id = _seed_receiver()
    public_id = _invite_foreign_parent(client, identity, receiver_id, share_cents=3600)
    _accept(public_id, receiver_id)  # OFF → accepted, no Debt
    assert _debts_for(public_id) == []

    assert _run_backfill() == 1

    debts = _debts_for(public_id)
    assert len(debts) == 1
    debt = debts[0]
    assert debt.principal_amount_cents == 3600  # the home-currency share
    assert debt.home_currency_code == "CNY"  # frozen from the invitation snapshot
    assert debt.original_currency_code is None  # USD provenance NOT copied
    assert debt.original_amount_minor is None
    assert debt.exchange_rate_to_cny is None
    assert debt.exchange_rate_date is None
    assert debt.exchange_rate_source is None
    assert debt.source_type == "bill_split"
    assert debt.source_id == public_id
