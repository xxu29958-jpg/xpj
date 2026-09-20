"""SQLite exercises the actual activity read projection, never PG write guarantees."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, create_engine, event, insert
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    BillSplitAgreementChange,
    BillSplitChangeProposal,
    BillSplitInvitation,
    Debt,
    DebtAdjustment,
    DebtForgiveness,
    DebtVoid,
    MemberRepaymentProposal,
    Repayment,
    RepaymentVoid,
)
from app.services.debt_service import list_debt_activity

WHEN = datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest.fixture
def records():
    # Copy column types only: this tests production SELECTs/DTOs, not PostgreSQL
    # constraints, triggers, locks, or command admission. Those use the HTTP file.
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for model in (Account, Debt, DebtAdjustment, DebtForgiveness, DebtVoid,
                  BillSplitInvitation, BillSplitChangeProposal, BillSplitAgreementChange,
                  MemberRepaymentProposal, Repayment, RepaymentVoid):
        Table(model.__tablename__, metadata, *(
            Column(column.name, JSON() if isinstance(column.type, JSONB) else column.type, primary_key=column.primary_key)
            for column in model.__table__.columns))
    metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Account(id=1, display_name="Alice"), Account(id=2, display_name="Bob"),
                    Account(id=3, display_name="Unrelated")])
        db.flush()
        yield db
    engine.dispose()


def _debt(db, *, id_=1, member=False):
    debt = Debt(id=id_, public_id=f"debt-{id_}", tenant_id="private-ledger", owner_account_id=1,
        created_by_account_id=1, direction="i_owe", counterparty_type="member" if member else "external",
        counterparty_account_id=2 if member else None, counterparty_label=None if member else "Bank",
        principal_amount_cents=50_000, home_currency_code="CNY", status="open",
        source_type="bill_split" if member else "manual", source_id=f"agreement-{id_}" if member else None,
        created_at=WHEN, updated_at=WHEN, row_version=1)
    db.add(debt)
    db.flush()
    return debt


def _repayment(db, debt, *, id_=1, at=WHEN, amount=4_000, **extra):
    repayment = Repayment(id=id_, public_id=f"repayment-{id_}", debt_id=debt.id, amount_cents=amount,
        paid_at=WHEN - timedelta(days=3), actor_account_id=1, idempotency_key=f"private-key-{id_}",
        created_at=at, **extra)
    db.add(repayment)
    db.flush()
    return repayment


def _proposal(db, debt, **extra):
    values = {"id": 1, "public_id": "proposal-1", "debt_id": debt.id, "debtor_account_id": 1,
        "creditor_account_id": 2, "proposed_by_account_id": 1, "proposed_amount_cents": 10_000,
        "home_currency_code": "CNY", "paid_at": WHEN - timedelta(days=3), "note": "Transfer for September",
        "status": "pending", "idempotency_key": "private-proposal-key", "created_at": WHEN,
        "expires_at": WHEN + timedelta(days=30)}
    values.update(extra)
    proposal = MemberRepaymentProposal(**values)
    db.add(proposal)
    db.flush()
    return proposal


def _read(db, debt, *, page=1, page_size=50, **extra):
    return list_debt_activity(db, tenant_id="private-ledger", actor_account_id=1,
        public_id=debt.public_id, page=page, page_size=page_size, **extra)


def _identity(item):
    return item.kind, item.public_id


def test_retained_adjustment_void_and_payment_keep_distinct_meanings(records):
    debt = _debt(records)
    payment = _repayment(records, debt, original_currency_code="USD", original_amount_minor=500,
        exchange_rate_to_cny=Decimal("8"), exchange_rate_date=WHEN, exchange_rate_source="manual")
    records.add_all([
        DebtAdjustment(public_id="adjustment", debt_id=debt.id, amount_cents=-1_000, reason="Correction",
            actor_account_id=1, idempotency_key="adjust-key", created_at=WHEN),
        RepaymentVoid(public_id="repayment-void", repayment_id=payment.id, reason="Duplicate transfer",
            actor_account_id=2, idempotency_key="void-key", created_at=WHEN),
        DebtVoid(public_id="debt-void", debt_id=debt.id, reason="Duplicate obligation",
            actor_account_id=1, idempotency_key="debt-void-key", created_at=WHEN),
    ])
    debt.status = "voided"
    records.flush()

    result = _read(records, debt)
    assert result.total == 5
    by_kind = {item.kind: item for item in result.items}
    assert set(by_kind) == {"created", "repayment", "repayment_void", "adjustment", "debt_void"}
    assert by_kind["created"].amount_cents == 50_000
    assert by_kind["adjustment"].amount_cents == -1_000
    assert by_kind["adjustment"].reason == "Correction"
    assert by_kind["debt_void"].amount_cents is None
    assert by_kind["debt_void"].reason == "Duplicate obligation"
    original = by_kind["repayment"].repayment
    assert original.amount_cents == 4_000 and original.status == "voided"
    assert original.original_currency_code == "USD" and original.original_amount_minor == 500
    assert original.exchange_rate_to_cny == Decimal("8")
    assert original.exchange_rate_source == "manual"
    assert original.paid_at.date() == (WHEN - timedelta(days=3)).date()
    assert by_kind["repayment_void"].repayment == original
    assert original.void_fact.public_id == "repayment-void"
    assert by_kind["repayment_void"].actor_display_name == "Bob"
    assert by_kind["repayment_void"].actor_is_you is False
    assert by_kind["created"].actor_display_name == "Alice" and by_kind["created"].actor_is_you


def test_partial_confirmation_links_one_fact_without_turning_proposals_into_payments(records):
    debt = _debt(records, member=True)
    payment = _repayment(records, debt, proposal_id=1)
    _proposal(records, debt, status="partially_confirmed", confirmed_amount_cents=4_000,
        committed_repayment_id=payment.id, resolved_at=WHEN, resolved_by_account_id=2)
    result = _read(records, debt)
    assert result.total == 4
    assert [item.kind for item in result.items] == ["proposal_resolved", "repayment", "proposal_created", "created"]
    proposals = [item for item in result.items if item.proposal is not None]
    assert {_identity(item) for item in proposals} == {
        ("proposal_created", "proposal-1"), ("proposal_resolved", "proposal-1")}
    for item in proposals:
        assert item.amount_cents is None and item.repayment is None
        assert item.proposal.proposed_amount_cents == 10_000
        assert item.proposal.confirmed_amount_cents == 4_000
        assert item.proposal.committed_repayment_public_id == payment.public_id
        assert item.proposal.status == "partially_confirmed"
    assert len([item for item in result.items if item.kind == "repayment"]) == 1
    assert result.items[0].actor_display_name == "Bob" and not result.items[0].actor_is_you


def test_forgiveness_keeps_its_snapshot_amount_and_does_not_become_repayment(records):
    debt = _debt(records, member=True)
    _repayment(records, debt)
    records.add(DebtForgiveness(public_id="forgiven", debt_id=debt.id, amount_cents=46_000,
        actor_account_id=2, idempotency_key="forgive-key", created_at=WHEN + timedelta(seconds=1)))
    debt.status = "cleared"
    records.flush()
    result = _read(records, debt)
    assert result.total == 3
    forgiven = result.items[0]
    assert forgiven.kind == "forgiveness" and forgiven.amount_cents == 46_000
    assert forgiven.repayment is None and forgiven.proposal is None
    assert len([item for item in result.items if item.kind == "repayment"]) == 1


def test_equal_timestamp_pages_are_stable_complete_and_can_reach_oldest(records):
    debt = _debt(records)
    for id_ in range(1, 7):
        _repayment(records, debt, id_=id_, amount=100)
    records.add(DebtAdjustment(public_id="adjustment", debt_id=debt.id, amount_cents=100,
        reason="Correction", actor_account_id=1, idempotency_key="adjust-key", created_at=WHEN))
    records.flush()
    pages = [_read(records, debt, page=page, page_size=3) for page in range(1, 4)]
    assert all(page.total == 8 and page.page_size == 3 for page in pages)
    assert [page.page for page in pages] == [1, 2, 3]
    identities = [_identity(item) for page in pages for item in page.items]
    assert identities == [*(('repayment', f'repayment-{i}') for i in range(6, 0, -1)),
                          ("adjustment", "adjustment"), ("created", debt.public_id)]
    assert len(set(identities)) == 8
    assert [_identity(item) for item in _read(records, debt, page=2, page_size=3).items] == identities[3:6]
    beyond = _read(records, debt, page=4, page_size=3)
    assert beyond.total == 8 and beyond.items == []


def test_focus_repayment_locates_real_old_page_and_rejects_other_debt(records):
    debt = _debt(records)
    for id_ in range(1, 7):
        _repayment(records, debt, id_=id_, amount=100)
    result = _read(records, debt, page_size=2, focus_repayment="repayment-1")
    assert result.page == 3 and result.total == 7
    assert "repayment-1" in [item.public_id for item in result.items if item.kind == "repayment"]
    other = _debt(records, id_=2)
    _repayment(records, other, id_=7)
    for public_id in ("repayment-7", "missing"):
        with pytest.raises(AppError) as error:
            _read(records, debt, page_size=2, focus_repayment=public_id)
        assert error.value.error == "repayment_not_found" and error.value.status_code == 404


@pytest.mark.parametrize("after_read", [2, 3, 4])
def test_focus_keeps_target_when_a_new_fact_arrives_between_reads(records, after_read):
    """Exercise read interleavings; real PG transaction guarantees are tested separately."""
    debt = _debt(records, member=True)
    for id_ in range(1, 7):
        _repayment(records, debt, id_=id_, amount=100)
    _proposal(records, debt, status="partially_confirmed", proposed_amount_cents=1_000,
        confirmed_amount_cents=100, committed_repayment_id=6,
        resolved_at=WHEN + timedelta(seconds=1), resolved_by_account_id=2)
    reads = 0
    inserted = False
    connection = records.connection()

    def arrive_after_read(conn, cursor, statement, parameters, context, executemany):
        nonlocal reads, inserted
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            reads += 1
        if inserted or reads != after_read:
            return
        inserted = True
        conn.execute(insert(Repayment).values(
            id=7, public_id="repayment-7", debt_id=debt.id, amount_cents=100,
            paid_at=WHEN, actor_account_id=1, idempotency_key="arriving-fact",
            created_at=WHEN + timedelta(seconds=2),
        ))

    event.listen(connection, "after_cursor_execute", arrive_after_read)
    try:
        result = _read(records, debt, page_size=3, focus_repayment="repayment-5")
    finally:
        event.remove(connection, "after_cursor_execute", arrive_after_read)
    assert inserted
    assert "repayment-5" in [item.public_id for item in result.items]


@pytest.mark.parametrize("status", ["pending", "expired"])
def test_unresolved_proposal_does_not_fabricate_expiry_resolution_or_local_intents(records, status):
    debt = _debt(records, member=True)
    proposal = _proposal(records, debt, status=status, expires_at=WHEN - timedelta(days=1))
    result = _read(records, debt)
    assert result.total == 2
    assert {item.kind for item in result.items} == {"created", "proposal_created"}
    assert next(item.proposal for item in result.items if item.proposal).status == status
    records.refresh(proposal)
    assert proposal.status == status and proposal.resolved_at is None


def test_superseded_proposal_links_survive_when_predecessor_is_on_an_older_page(records):
    debt = _debt(records, member=True)
    first = _proposal(records, debt, status="superseded", resolved_at=WHEN + timedelta(seconds=1))
    _proposal(records, debt, id=2, public_id="proposal-2", supersedes_proposal_id=first.id,
        created_at=WHEN + timedelta(seconds=2), idempotency_key="second-private-key")
    result = _read(records, debt, page_size=1)
    assert result.total == 4
    current = result.items[0]
    assert current.kind == "proposal_created" and current.public_id == "proposal-2"
    assert current.proposal.supersedes_proposal_public_id == "proposal-1"
    resolved = _read(records, debt, page=2, page_size=1).items[0]
    assert resolved.kind == "proposal_resolved" and resolved.proposal.status == "superseded"
    assert resolved.actor_display_name is None and not resolved.actor_is_you
    assert resolved.proposal.committed_repayment_public_id is None and resolved.amount_cents is None


def test_cross_ledger_participant_projection_has_no_private_identifiers(records):
    debt = _debt(records, member=True)
    _repayment(records, debt)
    _proposal(records, debt)
    result = list_debt_activity(records, tenant_id="participant-ledger", actor_account_id=2,
        public_id=debt.public_id, page=1, page_size=50)
    assert result.total == 3
    encoded = result.model_dump_json()
    for private in ("private-ledger", "idempotency_key", "actor_account_id", "debtor_account_id",
                    "creditor_account_id", "debt_id", "tenant_id", "ledger_id", "image_path", "private-key"):
        assert private not in encoded
    for tenant, actor in (("unrelated-ledger", 3), ("unrelated-ledger", 1)):
        with pytest.raises(AppError) as error:
            list_debt_activity(records, tenant_id=tenant, actor_account_id=actor,
                public_id=debt.public_id, page=1, page_size=50)
        assert error.value.error == "debt_not_found" and error.value.status_code == 404
