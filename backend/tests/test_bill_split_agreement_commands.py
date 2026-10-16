"""Short ORM business journeys; PG locks, migration and HTTP have separate gates."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, UniqueConstraint, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    ApiIdempotencyKey,
    BillSplitAgreementChange,
    BillSplitChangeProposal,
    BillSplitInvitation,
    Debt,
    DebtAdjustment,
    DebtForgiveness,
    DebtVoid,
    Expense,
    Ledger,
    LedgerCalendarRevision,
    MemberRepaymentProposal,
    Repayment,
    RepaymentVoid,
)
from app.schemas._bill_split_change import BillSplitChangeAcceptRequest, BillSplitChangeCreateRequest
from app.services.bill_split_service._agreement_commands import accept_bill_split_change, create_bill_split_change
from app.services.debt_service._fold import compute_paid, compute_remaining

WHEN = datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest.fixture
def agreement_db(monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def explicit_transactions(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        # SQLite's legacy driver otherwise commits a first SAVEPOINT on release.
        connection.exec_driver_sql("BEGIN")

    metadata = MetaData()
    models = (Account, Ledger, LedgerCalendarRevision, ApiIdempotencyKey, BillSplitInvitation, BillSplitChangeProposal, BillSplitAgreementChange,
              Debt, DebtAdjustment, DebtForgiveness, DebtVoid, Expense, MemberRepaymentProposal, Repayment, RepaymentVoid)
    for model in models:
        table = Table(model.__tablename__, metadata, *(Column(column.name,
            JSON() if isinstance(column.type, JSONB) else column.type, primary_key=column.primary_key)
            for column in model.__table__.columns))
        if model is ApiIdempotencyKey:
            table.append_constraint(UniqueConstraint("tenant_id", "idempotency_key"))
    metadata.create_all(engine)
    monkeypatch.setattr("app.services.bill_split_service._agreement_commands.resolve_write_capability", lambda db: None)
    with Session(engine) as db:
        db.add_all([Account(id=1, display_name="Receiver"), Account(id=2, display_name="Sender"),
                    Account(id=3, display_name="Ledger viewer")])
        for ledger_id, owner in (("receiver-private", 1), ("sender-private", 2)):
            db.add(Ledger(ledger_id=ledger_id, name=ledger_id, owner_account_id=owner, calendar_revision=1))
            db.add(LedgerCalendarRevision(ledger_id=ledger_id, revision=1, timezone_name="Asia/Shanghai",
                basis="user_selected", adopted_at=WHEN, actor_account_id=owner))
        db.add(BillSplitInvitation(id=1, public_id="invitation", sender_account_id=2,
            sender_ledger_id="sender-private", sender_expense_id=100, receiver_account_id=1,
            receiver_ledger_id="receiver-private", received_expense_id=200,
            amount_cents=4_000, home_currency_code="CNY", status="accepted",
            created_at=WHEN, accepted_at=WHEN, expires_at=WHEN + timedelta(days=7)))
        db.add_all([Expense(id=100, public_id="source", tenant_id="sender-private", amount_cents=10_000),
                    Expense(id=200, public_id="received", tenant_id="receiver-private", amount_cents=4_000)])
        db.add(Debt(id=1, public_id="original", tenant_id="receiver-private", owner_account_id=1,
            created_by_account_id=1, direction="i_owe", counterparty_type="member", counterparty_account_id=2,
            principal_amount_cents=4_000, home_currency_code="CNY", status="open", source_type="bill_split",
            source_id="invitation", created_at=WHEN, updated_at=WHEN, row_version=1))
        db.commit()
        yield db
    engine.dispose()


def _request(db, *, share, net, actor=1, supersedes=None):
    original = db.get(Debt, 1)
    returned = db.scalar(select(Debt).where(Debt.source_type == "bill_split_return"))
    return create_bill_split_change(db, tenant_id="receiver-private", actor_account_id=actor,
        public_id="original", payload=BillSplitChangeCreateRequest(new_share_amount_cents=share,
            settlement_net_amount_cents=net, reason="Both review the source refund",
            expected_row_version=original.row_version,
            expected_return_row_version=returned.row_version if returned else None,
            supersedes_proposal_public_id=supersedes))


def _accept(db, proposal, *, actor=2):
    return accept_bill_split_change(db, tenant_id="sender-private" if actor == 2 else "receiver-private",
        actor_account_id=actor, public_id="original", proposal_public_id=proposal.public_id,
        payload=BillSplitChangeAcceptRequest(expected_row_version=proposal.original_debt_row_version,
            expected_return_row_version=proposal.return_debt_row_version), idempotency_key=f"accept-{proposal.public_id}")


def _paid(db, debt_id, amount):
    db.add(Repayment(debt_id=debt_id, amount_cents=amount, actor_account_id=1,
        idempotency_key=f"paid-{debt_id}", paid_at=WHEN, created_at=WHEN))
    db.flush()


def test_existing_forgiveness_survives_a_new_agreement_without_fake_cash(agreement_db):
    db = agreement_db
    _paid(db, 1, 1_000)
    db.add(DebtForgiveness(debt_id=1, amount_cents=3_000, actor_account_id=2,
        idempotency_key="gift", created_at=WHEN))
    db.flush()
    proposal = _request(db, share=2_000, net=0)
    _accept(db, proposal)
    assert proposal.original_forgiven_amount_cents == 3_000
    assert compute_remaining(db, db.get(Debt, 1)) == 0
    assert compute_paid(db, db.get(Debt, 1)) == 1_000
    assert db.scalar(select(Debt).where(Debt.source_type == "bill_split_return")) is None


def test_proposer_cannot_accept_own_terms_and_stale_other_party_must_review_again(agreement_db):
    db = agreement_db
    proposal = _request(db, share=2_000, net=2_000)
    with pytest.raises(AppError) as own:
        _accept(db, proposal, actor=1)
    assert own.value.error == "split_change_other_party_only"
    db.get(Debt, 1).row_version += 1
    db.flush()
    with pytest.raises(AppError) as stale:
        _accept(db, proposal)
    assert stale.value.error == "state_conflict"
    assert proposal.status == "pending"
    assert not list(db.scalars(select(BillSplitAgreementChange)))


def test_same_ledger_reader_cannot_change_another_members_agreement(agreement_db):
    with pytest.raises(AppError) as denied:
        _request(agreement_db, share=2_000, net=2_000, actor=3)
    assert denied.value.error == "split_change_party_only"
