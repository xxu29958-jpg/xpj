"""codex P1: an archived ledger may not be a bill-split target.

A ledger archived via ADR-0038 disappears from every read surface — ledger
lists, auth, pairing, invitations all filter ``archived_at IS NULL``. Bill-split
must be no exception: accepting an invitation INTO an archived target ledger
(or initiating one FROM it) is rejected with 409 ``ledger_archived`` rather than
silently materialising a received expense in a dead ledger.

The guard lives in ``_load_writer_member`` (bill_split_service/_common.py), so a
single check covers accept-target, create-sender and cancel-sender paths. This
test exercises the accept-target path, which is the one that can resurrect a
ledger from the receiver's side.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Expense, Ledger, LedgerMember
from app.services.time_service import now_utc


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_receiver(name: str, ledger_id: str) -> int:
    """Create a second account + their own personal ledger where they are owner."""
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id=ledger_id, name=f"{name} 的账本", owner_account_id=account.id))
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="owner"))
        db.commit()
        return account.id


def _make_expense_for_owner(amount_cents: int = 5000) -> int:
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=amount_cents,
            merchant="Pizza Place",
            category="餐饮",
            source="iPhone截图",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(expense)
        db.commit()
        return expense.id


def test_accept_to_archived_ledger_409(client, *, identity) -> None:  # noqa: ARG001
    from app.errors import AppError
    from app.services import bill_split_service as bsplit

    receiver_account_id = _seed_receiver(name="B-arch", ledger_id="receiver_arch")
    expense_id = _make_expense_for_owner()
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
        )
        public_id = inv.public_id

    # Archive the target ledger after the invitation exists — it must now be
    # an invalid accept target even though the receiver is its owner.
    with SessionLocal() as db:
        target = db.scalar(select(Ledger).where(Ledger.ledger_id == "receiver_arch"))
        assert target is not None
        target.archived_at = now_utc()
        db.commit()

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_arch",
        )
    assert exc.value.error == "ledger_archived"
    assert exc.value.status_code == 409


def test_accept_to_active_ledger_still_succeeds(client, *, identity) -> None:  # noqa: ARG001
    """Positive guard: a non-archived target still accepts, proving the new
    archived check does not block the normal path."""
    from app.services import bill_split_service as bsplit

    receiver_account_id = _seed_receiver(name="B-live", ledger_id="receiver_live")
    expense_id = _make_expense_for_owner()
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
        )
        public_id = inv.public_id

    with SessionLocal() as db:
        _inv, received = bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_live",
        )
        assert received.tenant_id == "receiver_live"
        assert received.amount_cents == 2500
