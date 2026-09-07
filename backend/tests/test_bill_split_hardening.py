"""Additional bill split contract hardening tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal, engine
from app.errors import AppError
from app.models import BillSplitInvitation, Expense, Ledger, LedgerMember
from app.services import bill_split_service as bsplit
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc
from tests.test_bill_split import (
    _make_expense_for_owner,
    _owner_account_id,
    _seed_receiver,
    _split_headers,
)


def test_invitation_retry_after_peer_acceptance_keeps_the_original_result(
    client: TestClient, *, identity
) -> None:
    expense_id = _make_expense_for_owner(amount_cents=5000)
    receiver = _seed_receiver(name="B-lost-ack", ledger_id="receiver_lost_ack")
    headers = _split_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    payload = {"receiver_account_id": receiver, "amount_cents": 2000, "expected_row_version": 1}
    first = client.post(f"/api/expenses/{expense_id}/split-invite", headers=headers, json=payload)
    assert first.status_code == 200, first.json()
    original = first.json()

    # The sender loses this response while the recipient accepts the invitation.
    with SessionLocal() as db:
        accepted, received = bsplit.accept_invitation(
            db,
            public_id=original["public_id"],
            accepting_account_id=receiver,
            target_ledger_id="receiver_lost_ack",
        )
        received_id = received.id
        assert accepted.status == "accepted"
        db.execute(update(Expense).where(Expense.id == expense_id).values(merchant="Later correction", row_version=2))
        db.commit()

    replay = client.post(f"/api/expenses/{expense_id}/split-invite", headers=headers, json=payload)
    assert replay.status_code == 200, replay.json()
    assert replay.json()["public_id"] == original["public_id"]
    assert replay.json()["status"] == "accepted"
    changed = client.post(f"/api/expenses/{expense_id}/split-invite", headers=headers,
        json={**payload, "amount_cents": 2100})
    assert changed.status_code == 422
    assert changed.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        invitations = db.scalars(select(BillSplitInvitation).where(
            BillSplitInvitation.sender_expense_id == expense_id,
        )).all()
        assert len(invitations) == 1
        assert invitations[0].received_expense_id == received_id


def test_split_creation_rejects_changed_source_without_publishing_an_invitation(client: TestClient, *, identity) -> None:
    expense_id = _make_expense_for_owner()
    receiver = _seed_receiver(name="B-source-change", ledger_id="receiver_source_change")
    with SessionLocal() as db:
        db.execute(update(Expense).where(Expense.id == expense_id).values(merchant="Corrected source", row_version=2))
        db.commit()
    response = client.post(f"/api/expenses/{expense_id}/split-invite", headers=_split_headers(client, identity.app_headers),
        json={"receiver_account_id": receiver, "amount_cents": 2000, "expected_row_version": 1})
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"
    with SessionLocal() as db:
        assert db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.sender_expense_id == expense_id)) is None


def test_previous_split_protocol_requires_upgrade_before_body_validation(client: TestClient, *, identity) -> None:
    from app.runtime_compatibility_contract import TICKETBOX_API_VERSION_HEADER

    expense_id = _make_expense_for_owner()
    receiver = _seed_receiver(name="B-old-client", ledger_id="receiver_old_client")
    response = client.post(f"/api/expenses/{expense_id}/split-invite",
        headers={**identity.app_headers, TICKETBOX_API_VERSION_HEADER: "2026-09-06"},
        json={"receiver_account_id": receiver, "amount_cents": 2000})
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "client_upgrade_required"


def test_active_split_invitation_total_cannot_exceed_parent_expense(
    client: TestClient, *, identity
) -> None:
    expense_id = _make_expense_for_owner(amount_cents=5000)
    receiver_a = _seed_receiver(name="B-cap-a", ledger_id="receiver_cap_a")
    receiver_b = _seed_receiver(name="B-cap-b", ledger_id="receiver_cap_b")

    first = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=_split_headers(client, identity.app_headers),
        json={"expected_row_version": 1, "receiver_account_id": receiver_a, "amount_cents": 3000},
    )
    assert first.status_code == 200, first.json()

    second = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=_split_headers(client, identity.app_headers),
        json={"expected_row_version": 1, "receiver_account_id": receiver_b, "amount_cents": 2500},
    )
    assert second.status_code == 422
    assert second.json()["error"] == "split_total_exceeds_parent"


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="row-lock contention is only observable on the PostgreSQL lane; "
    "FOR UPDATE is a no-op on SQLite",
)
@pytest.mark.real_db
def test_create_invitation_row_locks_parent_expense(*, identity) -> None:
    """PG-only 债#1: ``create_invitation`` FOR-UPDATEs the parent expense so the
    active_split_total read + cap check + insert serialize against concurrent
    invites on the same parent (replacing the removed SQLite-only BEGIN IMMEDIATE
    writer guard). The ``.with_for_update()`` token itself is pinned by the
    cloud-hardening audit gate; this test pins the runtime effect — the create
    path serializes against a parent row lock on PG.

    Session A holds the parent's row lock without committing; a second
    ``create_invitation`` then cannot complete: its parent ``FOR UPDATE`` (and,
    failing that, its child INSERT's FK ``FOR KEY SHARE`` on the same parent)
    both conflict with A's lock. A short ``lock_timeout`` turns that contention
    into a deterministic ``OperationalError`` instead of a hang.
    """
    expense_id = _make_expense_for_owner(amount_cents=5000)
    receiver_account_id = _seed_receiver(name="B-lock", ledger_id="receiver_lock")

    holder = SessionLocal()
    try:
        # Session A acquires and holds FOR UPDATE on the parent expense row.
        holder.scalar(
            select(Expense).where(Expense.id == expense_id).with_for_update()
        )
        # Session B: a short lock_timeout turns the contended FOR UPDATE inside
        # create_invitation into a deterministic fast failure instead of a hang.
        with SessionLocal() as blocked, pytest.raises(OperationalError):
            blocked.execute(text("SET LOCAL lock_timeout = '500ms'"))
            bsplit.create_invitation(
                blocked,
                sender_account_id=_owner_account_id(),
                sender_ledger_id="owner",
                expense_id=expense_id,
                receiver_account_id=receiver_account_id,
                amount_cents=1000,
                idempotency_key=str(uuid4()), expected_row_version=1,
            )
    finally:
        holder.rollback()
        holder.close()


def test_reaccept_with_different_target_ledger_is_conflict() -> None:
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(
        name="B-idem-target",
        ledger_id="receiver_idem_target_a",
    )
    with SessionLocal() as db:
        db.add(
            Ledger(
                ledger_id="receiver_idem_target_b",
                name="B-idem-target backup ledger",
                owner_account_id=receiver_account_id,
            )
        )
        db.add(
            LedgerMember(
                ledger_id="receiver_idem_target_b",
                account_id=receiver_account_id,
                role="owner",
            )
        )
        db.commit()

    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
            idempotency_key=str(uuid4()), expected_row_version=1,
        )
        public_id = inv.public_id
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_idem_target_a",
        )

    with SessionLocal() as db, pytest.raises(AppError) as exc_info:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_idem_target_b",
        )
    assert exc_info.value.error == "state_conflict"
    assert exc_info.value.status_code == 409


def test_foreign_currency_split_lands_received_expense_in_home_currency() -> None:
    """The receiver owes the agreed share in the HOME currency. A USD parent
    must NOT leak its full-amount ``original_amount_minor`` / rate onto the
    received expense: a partial-amount row carrying the parent's full $ total
    breaks the ``amount_cents == original × rate`` invariant and is then
    frozen forever by ``IMMUTABLE_ON_SPLIT_RECEIVED``. The invitation keeps
    the parent snapshot for display; the received expense lands as a plain
    home-currency row (original == home, rate == 1)."""
    rate_date = date(2026, 5, 1)
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(
            tenant_id="owner",
            amount_cents=7000,
            home_currency_code="CNY",
            original_currency_code="USD",
            original_amount_minor=1000,
            exchange_rate_to_cny=Decimal("7.00000000"),
            exchange_rate_date=rate_date,
            exchange_rate_source="manual",
            merchant="Foreign Cafe",
            category="food",
            source="iphone_screenshot",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id

    receiver_account_id = _seed_receiver(
        name="B-fx",
        ledger_id="receiver_fx_snapshot",
    )

    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=3500,
            idempotency_key=str(uuid4()), expected_row_version=1,
        )
        # Invitation snapshot keeps the parent's original-currency context.
        assert inv.original_currency_code == "USD"
        assert inv.original_amount_minor == 1000
        assert inv.exchange_rate_to_cny == Decimal("7")
        assert inv.exchange_rate_date is not None
        assert inv.exchange_rate_date.date() == rate_date
        _inv, received = bsplit.accept_invitation(
            db,
            public_id=inv.public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_fx_snapshot",
        )
        received_id = received.id

    with SessionLocal() as db:
        received = db.scalar(
            select(Expense)
            .where(Expense.id == received_id)
            .where(Expense.tenant_id == "receiver_fx_snapshot")
        )
        assert received is not None
        assert received.amount_cents == 3500
        assert received.home_currency_code == "CNY"
        assert received.original_currency_code == "CNY"
        assert received.original_amount_minor == 3500
        assert received.exchange_rate_to_cny == Decimal("1")
        assert received.exchange_rate_source == "base"
        assert received.fx_status == "ready"
        assert received.exchange_rate_date is not None


@pytest.mark.real_db
def test_two_sessions_accept_race_creates_single_received_expense(*, identity) -> None:
    """ADR-0038 PR-C: two sessions hold the same pre-accept ('invited') read
    of one invitation. session_a accepts (creates the received expense +
    atomically claims the invitation); session_b then runs its stale-'invited'
    accept, whose expense INSERT trips the ``uq_expenses_split_origin_invitation``
    backstop → IntegrityError → rollback → re-read the now-'accepted'
    invitation and return session_a's expense. Net: exactly ONE received
    expense, the receiver ledger total is NOT doubled.

    Mirrors ``test_two_sessions_archive_race_idempotent_no_double_write``:
    because ``SessionLocal`` is ``expire_on_commit=False``, session_b's
    ``get_invitation`` returns its stale identity-mapped 'invited' row, so this
    exercises the **lost-claim recovery** branch (not the same-session fast
    path that ``test_accept_idempotent_returns_same_received_expense`` covers).
    """
    expense_id = _make_expense_for_owner(amount_cents=5000)
    receiver_account_id = _seed_receiver(name="B-race", ledger_id="receiver_race")
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
            idempotency_key=str(uuid4()), expected_row_version=1,
        )
        public_id = inv.public_id

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        row_b = session_b.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert row_a is not None and row_b is not None
        assert row_a.status == "invited" and row_b.status == "invited"

        _inv_a, exp_a = bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_race",
        )
        exp_a_id = exp_a.id

        _inv_b, exp_b = bsplit.accept_invitation(
            session_b,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_race",
        )
        # Idempotent convergence: session_b returns session_a's expense.
        assert exp_b.id == exp_a_id
    finally:
        session_a.close()
        session_b.close()

    with SessionLocal() as db:
        received = list(
            db.scalars(
                select(Expense)
                .where(Expense.split_origin_invitation_id == public_id)
                .where(Expense.tenant_id == "receiver_race")
            )
        )
    assert len(received) == 1
    assert received[0].id == exp_a_id
    assert received[0].amount_cents == 2500


def test_accept_claim_update_is_guarded_by_invited_status(*, identity) -> None:
    """The atomic claim only flips an invitation while it is still 'invited' —
    a second guarded UPDATE matches 0 rows. This pins the application-level
    guard inside ``accept_invitation`` independently of the partial-unique DB
    backstop, so the SELECT-then-write regression can't silently return."""
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(name="B-claim", ledger_id="receiver_claim")
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
            idempotency_key=str(uuid4()), expected_row_version=1,
        )
        public_id = inv.public_id

    with SessionLocal() as db:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_claim",
        )

    with SessionLocal() as db:
        rowcount = db.execute(
            update(BillSplitInvitation)
            .where(BillSplitInvitation.public_id == public_id)
            .where(BillSplitInvitation.status == "invited")
            .values(status="accepted")
        ).rowcount
        db.rollback()
    assert rowcount == 0
