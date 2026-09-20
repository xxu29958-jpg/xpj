"""Real PostgreSQL migration and immutable-history probes; never executed on SQLite."""

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database import SessionLocal, engine
from app.models import (
    Account,
    BillSplitAgreementChange,
    BillSplitChangeProposal,
    BillSplitInvitation,
    Debt,
    Expense,
    Ledger,
    LedgerMember,
)
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority
from tests.test_bill_split_agreement_models import proposal_values

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260920_0002"
_HEAD = "20260920_0003"


def _seed_accepted_split():
    sender_id, sender_member_id = seed_owner()
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        receiver = Account(display_name="Agreement receiver")
        db.add(receiver)
        db.flush()
        db.add(Ledger(ledger_id="agreement-receiver", name="Private receiver", owner_account_id=receiver.id))
        db.flush()
        member = LedgerMember(ledger_id="agreement-receiver", account_id=receiver.id, role="owner")
        db.add(member)
        source = Expense(tenant_id="owner", amount_cents=100, original_amount_minor=100,
            original_currency_code="CNY", home_currency_code="CNY", category="其他", merchant="Source",
            source="manual", status="confirmed", confirmed_at=datetime.now(UTC))
        received = Expense(tenant_id="agreement-receiver", amount_cents=40, original_amount_minor=40,
            original_currency_code="CNY", home_currency_code="CNY", category="其他", merchant="Source",
            source="bill_split_received", status="confirmed", confirmed_at=datetime.now(UTC))
        db.add_all([source, received])
        db.flush()
        invitation = BillSplitInvitation(sender_account_id=sender_id, sender_ledger_id="owner",
            sender_member_id=sender_member_id, sender_expense_id=source.id, sender_display_name="Sender",
            receiver_account_id=receiver.id, receiver_ledger_id="agreement-receiver", receiver_member_id=member.id,
            received_expense_id=received.id, amount_cents=40, home_currency_code="CNY", original_currency_code="CNY",
            original_amount_minor=100, status="accepted", accepted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=7))
        db.add(invitation)
        db.flush()
        received.split_origin_invitation_id = invitation.public_id
        debt = Debt(tenant_id="agreement-receiver", owner_account_id=receiver.id, created_by_account_id=receiver.id,
            direction="i_owe", counterparty_type="member", counterparty_account_id=sender_id,
            principal_amount_cents=40, home_currency_code="CNY", source_type="bill_split", source_id=invitation.public_id)
        db.add(debt)
        db.flush()
        return {"invitation_id": invitation.id, "source_id": invitation.public_id, "debt_id": debt.id,
                "sender_id": sender_id, "receiver_id": receiver.id}


@pytest.fixture
def agreement_edge():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        yield _seed_accepted_split()
    finally:
        reset_schema()


def _original_rows():
    with engine.connect() as db:
        return {table: list(db.scalars(text(f"SELECT to_jsonb({table}) FROM {table} ORDER BY id")))
                for table in ("debts", "bill_split_invitations", "expenses")}


def _proposal(edge):
    return proposal_values(invitation_id=edge["invitation_id"], original_debt_id=edge["debt_id"],
                           proposed_by_account_id=edge["sender_id"])


def _create_return(db, edge):
    debt = Debt(tenant_id="agreement-receiver", owner_account_id=edge["receiver_id"],
        created_by_account_id=edge["receiver_id"], direction="owed_to_me", counterparty_type="member",
        counterparty_account_id=edge["sender_id"], principal_amount_cents=20, home_currency_code="CNY",
        source_type="bill_split_return", source_id=edge["source_id"])
    db.add(debt)
    db.flush()
    return debt.id


def test_empty_edge_preserves_existing_facts_and_round_trips(agreement_edge):
    before = _original_rows()
    run_alembic(command.upgrade, _HEAD)
    assert _original_rows() == before
    columns = {column["name"]: column for column in inspect(engine).get_columns("debts")}
    assert columns["source_type"]["type"].length == 32
    with engine.connect() as db:
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD
        assert db.scalar(text("SELECT count(*) FROM bill_split_change_proposals")) == 0
        assert db.scalar(text("SELECT count(*) FROM bill_split_agreement_changes")) == 0
    run_alembic(command.downgrade, _PARENT)
    assert _original_rows() == before
    assert not inspect(engine).has_table("bill_split_change_proposals")
    assert next(col for col in inspect(engine).get_columns("debts") if col["name"] == "source_type")["type"].length == 16
    with engine.connect() as db:
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _PARENT


def test_proposal_and_accepted_history_are_fenced_and_immutable(agreement_edge):
    edge = agreement_edge
    run_alembic(command.upgrade, _HEAD)
    with pytest.raises(DBAPIError, match="currency"), SessionLocal.begin() as db:
        db.add(BillSplitChangeProposal(**_proposal(edge)))
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        proposal = BillSplitChangeProposal(**_proposal(edge))
        db.add(proposal)
        db.flush()
        proposal_id = proposal.id
    with pytest.raises(IntegrityError, match="uq_bscp_one_pending"), SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        db.add(BillSplitChangeProposal(**_proposal(edge)))
    for assignment in ("new_share_amount_cents = 1", "reason = 'rewritten'", "original_paid_amount_cents = 0"):
        with pytest.raises(DBAPIError, match="proposal evidence is immutable"), SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text(f"UPDATE bill_split_change_proposals SET {assignment} WHERE id = :id"), {"id": proposal_id})
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        proposal = db.get(BillSplitChangeProposal, proposal_id)
        proposal.status, proposal.resolved_at, proposal.resolved_by_account_id = "accepted", datetime.now(UTC), edge["receiver_id"]
        return_id = _create_return(db, edge)
        db.add(BillSplitAgreementChange(proposal_id=proposal_id, invitation_id=edge["invitation_id"],
            original_debt_id=edge["debt_id"], return_debt_id=return_id, share_before_amount_cents=40,
            new_share_amount_cents=20, settlement_net_amount_cents=-20,
            proposed_by_account_id=edge["sender_id"], accepted_by_account_id=edge["receiver_id"]))
        db.add(BillSplitChangeProposal(**_proposal(edge)))
    for statement, message in (
        ("UPDATE bill_split_change_proposals SET status = 'rejected' WHERE id = :id", "proposal evidence is immutable"),
        ("DELETE FROM bill_split_change_proposals WHERE id = :id", "proposal evidence is immutable"),
        ("UPDATE bill_split_agreement_changes SET new_share_amount_cents = 1", "changes are append-only"),
        ("DELETE FROM bill_split_agreement_changes", "changes are append-only"),
    ):
        with pytest.raises(DBAPIError, match=message), SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text(statement), {"id": proposal_id})
    with pytest.raises(IntegrityError, match="uq_debts_source"), SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        _create_return(db, edge)
    with pytest.raises(RuntimeError, match="cannot discard split agreement evidence"):
        run_alembic(command.downgrade, _PARENT)
    with engine.connect() as db:
        assert db.scalar(select(BillSplitChangeProposal.original_paid_amount_cents).where(BillSplitChangeProposal.id == proposal_id)) == 40
        assert db.scalar(text("SELECT count(*) FROM bill_split_agreement_changes")) == 1
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == _HEAD


def test_return_identity_alone_prevents_lossy_downgrade(agreement_edge):
    run_alembic(command.upgrade, _HEAD)
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        _create_return(db, agreement_edge)
    with pytest.raises(RuntimeError, match="cannot discard split return debt identity"):
        run_alembic(command.downgrade, _PARENT)
    with engine.connect() as db:
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD
