"""Short constraint probes; PostgreSQL trigger execution has its own migration test."""

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, Table, create_engine, insert, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

from app.models import BillSplitAgreementChange, BillSplitChangeProposal, Debt
from app.money_contract import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX


@pytest.fixture
def storage():
    metadata = MetaData()
    for name in ("accounts", "debts", "debt_adjustments", "bill_split_invitations"):
        Table(name, metadata, Column("id", Integer, primary_key=True))
    tables = [model.__table__.to_metadata(metadata) for model in (BillSplitChangeProposal, BillSplitAgreementChange)]
    indexes = [index for table in tables for index in table.indexes]
    for table in tables:
        table.indexes.clear()
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("PRAGMA foreign_keys=ON"))
        metadata.create_all(db)
        # Execute the actual PG partial-index predicate; SQLite otherwise ignores
        # postgresql_where and would accidentally exercise a full unique index.
        for index in indexes:
            db.exec_driver_sql(str(CreateIndex(index).compile(dialect=postgresql.dialect())))
        for name in ("accounts", "debts", "debt_adjustments", "bill_split_invitations"):
            db.execute(insert(metadata.tables[name]), [{"id": 1}, {"id": 2}])
        yield db, metadata
    engine.dispose()


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


def test_only_one_pending_proposal_per_invitation_and_resolved_history_survives(storage):
    db, metadata = storage
    table = metadata.tables["bill_split_change_proposals"]
    first = db.execute(insert(table).values(**proposal_values())).inserted_primary_key[0]
    with pytest.raises(IntegrityError):
        db.execute(insert(table).values(**proposal_values()))
    db.execute(table.update().where(table.c.id == first).values(
        status="withdrawn", resolved_at=datetime.now(UTC), resolved_by_account_id=1))
    db.execute(insert(table).values(**proposal_values()))
    assert len(db.execute(table.select()).all()) == 2


@pytest.mark.parametrize("changes", [
    {"new_share_amount_cents": -1}, {"share_before_amount_cents": MONEY_MINOR_MAX + 1},
    {"settlement_net_amount_cents": MONEY_MINOR_MAX + 1},
    {"original_paid_amount_cents": MONEY_AGGREGATE_MAX + 1},
    {"return_forgiven_amount_cents": -1},
    {"settlement_before_net_amount_cents": -MONEY_AGGREGATE_MAX - 1},
    {"status": "invented"}, {"original_debt_row_version": 0},
    {"return_debt_id": 2}, {"return_debt_row_version": 1},
    {"return_debt_id": 1, "return_debt_row_version": 1},
    {"reason": ""}, {"status": "accepted"}, {"invitation_id": 999},
])
def test_invalid_proposal_cannot_be_stored(storage, changes):
    db, metadata = storage
    with pytest.raises(IntegrityError):
        db.execute(insert(metadata.tables["bill_split_change_proposals"]).values(**proposal_values(**changes)))


def test_zero_share_signed_settlement_and_large_fold_snapshots_are_valid(storage):
    db, metadata = storage
    db.execute(insert(metadata.tables["bill_split_change_proposals"]).values(**proposal_values(
        new_share_amount_cents=0, settlement_net_amount_cents=-MONEY_MINOR_MAX,
        original_paid_amount_cents=MONEY_AGGREGATE_MAX,
        settlement_before_net_amount_cents=-MONEY_AGGREGATE_MAX)))


def test_acceptance_is_unique_and_retains_both_adjustment_links(storage):
    db, metadata = storage
    proposal = metadata.tables["bill_split_change_proposals"]
    proposal_id = db.execute(insert(proposal).values(**proposal_values())).inserted_primary_key[0]
    values = {"public_id": str(uuid4()), "proposal_id": proposal_id, "invitation_id": 1,
        "share_before_amount_cents": 40, "new_share_amount_cents": 20, "settlement_net_amount_cents": -20,
        "original_debt_id": 1, "return_debt_id": 2,
        "original_adjustment_id": 1, "return_adjustment_id": 2,
        "proposed_by_account_id": 1, "accepted_by_account_id": 2, "created_at": datetime.now(UTC)}
    table = metadata.tables["bill_split_agreement_changes"]
    db.execute(insert(table).values(**values))
    with pytest.raises(IntegrityError):
        db.execute(insert(table).values(**{**values, "public_id": str(uuid4())}))


def test_return_debt_source_has_its_own_identity_but_still_requires_a_source():
    assert Debt.__table__.c.source_type.type.length >= len("bill_split_return")
    checks = {constraint.name: str(constraint.sqltext) for constraint in Debt.__table__.constraints
              if hasattr(constraint, "sqltext")}
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE probe (source_type TEXT NOT NULL, source_id TEXT, "
            "CHECK (" + checks["ck_debts_source_type_valid"] + "), CHECK (" +
            checks["ck_debts_bill_split_has_source_id"] + "), UNIQUE(source_type, source_id))")
        for kind in ("bill_split", "bill_split_return"):
            db.execute(text("INSERT INTO probe VALUES (:kind, 'same-invitation')"), {"kind": kind})
        for kind, source in (("bill_split_return", None), ("manual", "source"), ("unknown", None)):
            with pytest.raises(IntegrityError):
                db.execute(text("INSERT INTO probe VALUES (:kind, :source)"), {"kind": kind, "source": source})
    engine.dispose()


def test_frozen_migration_tables_and_indexes_match_current_models(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20260920_0003_bill_split_agreements.py"
    spec = spec_from_file_location("split_agreement_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    metadata = MetaData()

    class CaptureOperations:
        @staticmethod
        def f(name):
            return name

        @staticmethod
        def create_table(name, *parts):
            Table(name, metadata, *parts)

        @staticmethod
        def create_index(name, table, columns, **options):
            Index(name, *(metadata.tables[table].c[column] for column in columns), **options)

    monkeypatch.setattr(module, "op", CaptureOperations)
    module._create_tables()
    dialect = postgresql.dialect()
    for model in (BillSplitChangeProposal, BillSplitAgreementChange):
        table = model.__table__
        frozen = metadata.tables[table.name]
        assert [(c.name, str(c.type), c.nullable) for c in frozen.columns] == [
            (c.name, str(c.type), c.nullable) for c in table.columns]
        assert {c.name: str(c.sqltext) for c in frozen.constraints if hasattr(c, "sqltext")} == {
            c.name: str(c.sqltext) for c in table.constraints if hasattr(c, "sqltext")}
        assert {str(CreateIndex(index).compile(dialect=dialect)) for index in frozen.indexes} == {
            str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes}
