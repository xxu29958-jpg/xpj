"""PostgreSQL projection edge cases not repeated by the HTTP command journeys."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, insert

from app.database import SessionLocal
from app.errors import AppError
from app.models import Debt, DebtAdjustment, MemberRepaymentProposal, Repayment
from app.services.currency_binding_service import resolve_write_capability
from app.services.debt_service import list_debt_activity
from tests.bill_split_test_support import _seed_receiver

WHEN = datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest.fixture
def records(identity):
    actors = {"Alice": _seed_receiver("Alice", "private-ledger"),
              "Bob": _seed_receiver("Bob", "participant-ledger")}
    with SessionLocal() as db:
        resolve_write_capability(db)
        yield db, actors


def _debt(db, actors, *, id_=1, member=False):
    debt = Debt(id=id_, public_id=f"debt-{id_}", tenant_id="private-ledger", owner_account_id=actors["Alice"],
        created_by_account_id=actors["Alice"], direction="i_owe", counterparty_type="member" if member else "external",
        counterparty_account_id=actors["Bob"] if member else None, counterparty_label=None if member else "Bank",
        principal_amount_cents=50_000, home_currency_code="CNY", status="open",
        source_type="bill_split" if member else "manual", source_id=f"agreement-{id_}" if member else None,
        created_at=WHEN, updated_at=WHEN, row_version=1)
    db.add(debt)
    db.flush()
    return debt


def _repayment(db, actors, debt, *, id_=1, at=WHEN, amount=4_000, **extra):
    repayment = Repayment(id=id_, public_id=f"repayment-{id_}", debt_id=debt.id, amount_cents=amount,
        paid_at=WHEN - timedelta(days=3), actor_account_id=actors["Alice"], idempotency_key=f"private-key-{id_}",
        created_at=at, **extra)
    db.add(repayment)
    db.flush()
    return repayment


def _proposal(db, actors, debt, **extra):
    values = {"id": 1, "public_id": "proposal-1", "debt_id": debt.id, "debtor_account_id": actors["Alice"],
        "creditor_account_id": actors["Bob"], "proposed_by_account_id": actors["Alice"], "proposed_amount_cents": 10_000,
        "home_currency_code": "CNY", "paid_at": WHEN - timedelta(days=3), "note": "Transfer for September",
        "status": "pending", "idempotency_key": "private-proposal-key", "created_at": WHEN,
        "expires_at": WHEN + timedelta(days=30)}
    values.update(extra)
    proposal = MemberRepaymentProposal(**values)
    db.add(proposal)
    db.flush()
    return proposal


def _read(db, actors, debt, *, page=1, page_size=50, **extra):
    return list_debt_activity(db, tenant_id="private-ledger", actor_account_id=actors["Alice"],
        public_id=debt.public_id, page=page, page_size=page_size, **extra)


def _identity(item):
    return item.kind, item.public_id


def test_equal_timestamp_pages_are_stable_complete_and_can_reach_oldest(records):
    db, actors = records
    debt = _debt(db, actors)
    for id_ in range(1, 7):
        _repayment(db, actors, debt, id_=id_, amount=100)
    db.add(DebtAdjustment(public_id="adjustment", debt_id=debt.id, amount_cents=100,
        reason="Correction", actor_account_id=actors["Alice"], idempotency_key="adjust-key", created_at=WHEN))
    db.flush()
    pages = [_read(db, actors, debt, page=page, page_size=3) for page in range(1, 4)]
    assert all(page.total == 8 and page.page_size == 3 for page in pages)
    assert [page.page for page in pages] == [1, 2, 3]
    identities = [_identity(item) for page in pages for item in page.items]
    assert identities == [*(('repayment', f'repayment-{i}') for i in range(6, 0, -1)),
                          ("adjustment", "adjustment"), ("created", debt.public_id)]
    assert len(set(identities)) == 8
    assert [_identity(item) for item in _read(db, actors, debt, page=2, page_size=3).items] == identities[3:6]
    beyond = _read(db, actors, debt, page=4, page_size=3)
    assert beyond.total == 8 and beyond.items == []


@pytest.mark.parametrize("after_read", [2, 3, 4])
def test_focus_keeps_target_when_a_new_fact_arrives_between_reads(records, after_read):
    """Exercise read interleavings; real PG transaction guarantees are tested separately."""
    db, actors = records
    debt = _debt(db, actors, member=True)
    for id_ in range(1, 7):
        _repayment(db, actors, debt, id_=id_, amount=100)
    _proposal(db, actors, debt, status="partially_confirmed", proposed_amount_cents=1_000,
        confirmed_amount_cents=100, committed_repayment_id=6,
        resolved_at=WHEN + timedelta(seconds=1), resolved_by_account_id=actors["Bob"])
    reads = 0
    inserted = False
    connection = db.connection()

    def arrive_after_read(conn, cursor, statement, parameters, context, executemany):
        nonlocal reads, inserted
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            reads += 1
        if inserted or reads != after_read:
            return
        inserted = True
        conn.execute(insert(Repayment).values(
            id=7, public_id="repayment-7", debt_id=debt.id, amount_cents=100,
            paid_at=WHEN, actor_account_id=actors["Alice"], idempotency_key="arriving-fact",
            created_at=WHEN + timedelta(seconds=2),
        ))

    event.listen(connection, "after_cursor_execute", arrive_after_read)
    try:
        result = _read(db, actors, debt, page_size=3, focus_repayment="repayment-5")
    finally:
        event.remove(connection, "after_cursor_execute", arrive_after_read)
    assert inserted
    assert "repayment-5" in [item.public_id for item in result.items]


@pytest.mark.parametrize("status", ["pending", "expired"])
def test_unresolved_proposal_does_not_fabricate_expiry_resolution_or_local_intents(records, status):
    db, actors = records
    debt = _debt(db, actors, member=True)
    proposal = _proposal(db, actors, debt, status=status, expires_at=WHEN - timedelta(days=1))
    result = _read(db, actors, debt)
    assert result.total == 2
    assert {item.kind for item in result.items} == {"created", "proposal_created"}
    assert next(item.proposal for item in result.items if item.proposal).status == status
    db.refresh(proposal)
    assert proposal.status == status and proposal.resolved_at is None


def test_superseded_proposal_links_survive_when_predecessor_is_on_an_older_page(records):
    db, actors = records
    debt = _debt(db, actors, member=True)
    first = _proposal(db, actors, debt, status="superseded", resolved_at=WHEN + timedelta(seconds=1))
    _proposal(db, actors, debt, id=2, public_id="proposal-2", supersedes_proposal_id=first.id,
        created_at=WHEN + timedelta(seconds=2), idempotency_key="second-private-key")
    result = _read(db, actors, debt, page_size=1)
    assert result.total == 4
    current = result.items[0]
    assert current.kind == "proposal_created" and current.public_id == "proposal-2"
    assert current.proposal.supersedes_proposal_public_id == "proposal-1"
    resolved = _read(db, actors, debt, page=2, page_size=1).items[0]
    assert resolved.kind == "proposal_resolved" and resolved.proposal.status == "superseded"
    assert resolved.actor_display_name is None and not resolved.actor_is_you
    assert resolved.proposal.committed_repayment_public_id is None and resolved.amount_cents is None


def test_same_ledger_read_without_viewer_keeps_unattributed_resolution(records):
    db, actors = records
    debt = _debt(db, actors, member=True)
    _proposal(db, actors, debt, status="superseded", resolved_at=WHEN + timedelta(seconds=1))
    result = list_debt_activity(db, tenant_id=debt.tenant_id, actor_account_id=None,
        public_id=debt.public_id, page=1, page_size=50)
    assert result.total == 3
    assert {item.kind for item in result.items} == {"created", "proposal_created", "proposal_resolved"}
    resolved = next(item for item in result.items if item.kind == "proposal_resolved")
    assert resolved.actor_display_name is None
    assert not any(item.actor_is_you for item in result.items)
    for actor in (actors["Alice"], None):
        with pytest.raises(AppError) as error:
            list_debt_activity(db, tenant_id="unrelated-ledger", actor_account_id=actor,
                public_id=debt.public_id, page=1, page_size=50)
        assert error.value.error == "debt_not_found" and error.value.status_code == 404
