"""Real PostgreSQL qualification for calendar shape and atomic compatibility adoption."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database import SessionLocal, engine
from app.models import (
    BillSplitInvitation,
    CsvImportBatch,
    CsvImportRow,
    Expense,
    ExpenseOffsetFact,
    Ledger,
    LedgerCalendarRevision,
)
from app.services.ledger_calendar_service import adopt_ledger_calendar, calendar_revision, current_calendar
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test
from tests._infra.currency import activate_test_currency_authority
from tests._infra.env import ADMIN_TEST_DATABASE_URL

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260919_0001"
_HEAD = "20260920_0001"
_METADATA = ("calendar_revision", "user_local_date", "time_precision", "source_timezone",
             "source_utc_offset_seconds", "accounting_date_basis")


def _run(action, revision):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    run_alembic_for_test(engine, config, action, revision)


def _seed():
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        account = db.scalar(text("INSERT INTO accounts (public_id, display_name, created_at) "
                                 "VALUES (:id, 'Calendar owner', CURRENT_TIMESTAMP) RETURNING id"), {"id": str(uuid4())})
        for ledger in ("calendar-live", "calendar-archived"):
            db.execute(text("INSERT INTO ledgers (ledger_id, name, owner_account_id, created_at, archived_at) "
                            "VALUES (:ledger, :name, :owner, CURRENT_TIMESTAMP, :archived_at)"),
                       {"ledger": ledger, "name": ledger, "owner": account,
                        "archived_at": "2026-06-01T00:00:00Z" if ledger == "calendar-archived" else None})
        roots = []
        for instant, confirmed in (("2026-04-30T16:30:00Z", "2026-05-03T00:00:00Z"),
                                   (None, "2026-04-30T16:30:00Z"), (None, None)):
            roots.append(db.scalar(text("""
                INSERT INTO expenses (public_id, tenant_id, amount_cents, original_amount_minor,
                    merchant, category, source, duplicate_status, status, expense_time, confirmed_at,
                    created_at, updated_at, row_version, fact_revision)
                VALUES (:id, 'calendar-live', 10000, 10000, 'Original merchant', '其他', 'manual',
                    'none', 'confirmed', :instant, :confirmed, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 7, 1)
                RETURNING id
            """), {"id": str(uuid4()), "instant": instant, "confirmed": confirmed}))
        db.execute(text("""
            INSERT INTO expense_offset_facts (public_id, tenant_id, expense_id, kind,
                original_currency_code, original_amount_minor, home_currency_code, amount_cents,
                accounting_date, category, reason, created_actor_account_id, created_at, updated_at)
            VALUES (:id, 'calendar-live', :root, 'refund', 'CNY', 1000, 'CNY', 1000,
                '2026-05-01', '其他', 'Original refund', :owner, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"id": str(uuid4()), "root": roots[0], "owner": account})
        db.execute(text("""
            INSERT INTO expense_offset_revisions (public_id, tenant_id, expense_id, offset_id,
                revision_number, change_kind, reason, idempotency_key, actor_account_id, after_snapshot,
                resulting_row_version, created_at)
            SELECT :id, tenant_id, expense_id, id, 1, 'created', reason, :key, :owner,
                to_jsonb(expense_offset_facts)::json, row_version, CURRENT_TIMESTAMP FROM expense_offset_facts
        """), {"id": str(uuid4()), "key": str(uuid4()), "owner": account})
        db.execute(text("""
            INSERT INTO expense_revisions (public_id, tenant_id, expense_id, revision_number,
                change_kind, reason, idempotency_key, actor_account_id, changed_fields, after_snapshot,
                resulting_row_version, created_at)
            SELECT :id, tenant_id, id, 1, 'confirmed', 'Original', :key, :owner, '[]'::json,
                to_jsonb(expenses)::json, row_version, CURRENT_TIMESTAMP FROM expenses WHERE id = :root
        """), {"id": str(uuid4()), "key": str(uuid4()), "owner": account, "root": roots[0]})
        member = db.scalar(text("INSERT INTO ledger_members (ledger_id, account_id, role, created_at) "
                                 "VALUES ('calendar-live', :owner, 'owner', CURRENT_TIMESTAMP) RETURNING id"), {"owner": account})
        db.execute(text("""
            INSERT INTO bill_split_invitations (public_id, sender_account_id, sender_ledger_id,
                sender_member_id, sender_expense_id, sender_display_name, receiver_account_id,
                amount_cents, home_currency_code, original_currency_code, expense_time_snapshot,
                expires_at, created_at)
            VALUES (:id, :owner, 'calendar-live', :member, :root, 'Original owner', :owner,
                2000, 'CNY', 'CNY', '2026-04-30T16:30:00Z', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"id": str(uuid4()), "owner": account, "member": member, "root": roots[0]})
        batch = db.scalar(text("""
            INSERT INTO csv_import_batches (public_id, tenant_id, file_name, status, total_rows,
                valid_rows, error_rows, applied_rows, inserted_count, created_at, updated_at)
            VALUES (:id, 'calendar-live', 'original.csv', 'parsed', 1, 1, 0, 0, 0,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id
        """), {"id": str(uuid4())})
        db.execute(text("""
            INSERT INTO csv_import_rows (tenant_id, batch_id, line_number, status,
                original_currency_code, home_currency_code, amount_cents, category, source,
                expense_time, created_at, updated_at)
            VALUES ('calendar-live', :batch, 2, 'valid', 'CNY', 'CNY', 100, '其他', 'CSV',
                '2026-04-30T16:30:00Z', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"batch": batch})
    return roots


def _snapshot():
    with engine.connect() as db:
        return {table: [dict(row) for row in db.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
                for table in ("ledgers", "expenses", "expense_offset_facts", "expense_revisions",
                              "expense_offset_revisions", "bill_split_invitations", "csv_import_batches", "csv_import_rows")}


@pytest.fixture
def calendar_edge():
    reset_public_schema(engine)
    try:
        _run(command.upgrade, _PARENT)
        roots = _seed()
        yield roots, _snapshot()
    finally:
        reset_public_schema(engine)


def _without_calendar(snapshot):
    for row in snapshot["csv_import_batches"]:
        assert row.pop("calendar_revision") is None
    for row in snapshot["csv_import_rows"]:
        assert row.pop("time_input") is None
        assert row.pop("expense_time_input") is None
    for row in snapshot["bill_split_invitations"]:
        assert row.pop("accounting_time_snapshot") is None
    for row in snapshot["ledgers"]:
        row.pop("calendar_revision")
    for table in ("expenses", "expense_offset_facts"):
        for row in snapshot[table]:
            for key in _METADATA:
                row.pop(key)
            if table == "expenses":
                row.pop("accounting_date")
    return snapshot


def _set_currency_state(state):
    if state == "ACTIVE":
        return
    admin = create_engine(make_url(ADMIN_TEST_DATABASE_URL).set(database=engine.url.database))
    try:
        with admin.begin() as db:
            db.execute(text("ALTER TABLE installation_currency_bindings DISABLE TRIGGER trg_currency_binding_update_delete"))
            db.execute(text("UPDATE installation_currency_bindings SET state = :state, home_currency_code = NULL, "
                            "minor_unit_exponent = NULL, rounding_mode = NULL, binding_revision = 0, provenance = NULL, "
                            "evidence_sha256 = NULL, activated_at = NULL WHERE singleton_id = 1"), {"state": state})
            db.execute(text("ALTER TABLE installation_currency_bindings ENABLE TRIGGER trg_currency_binding_update_delete"))
    finally:
        admin.dispose()


def test_calendar_shape_preserves_history_and_empty_edge_round_trips(calendar_edge):
    _, original = calendar_edge
    _run(command.upgrade, _HEAD)
    assert _without_calendar(_snapshot()) == original
    _run(command.downgrade, _PARENT)
    assert _snapshot() == original
    assert "ledger_calendar_revisions" not in inspect(engine).get_table_names()
    with engine.connect() as db:
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _PARENT

    # Historical round-trip above stays on its original edge. Current ORM shape
    # includes later expansions and must be compared with the current schema.
    _run(command.upgrade, "head")
    inspector = inspect(engine)
    # PostgreSQL stores unqualified FLOAT as float8 and reflects its full name.
    postgresql_aliases = {"FLOAT": "DOUBLE PRECISION"}
    for model in (Ledger, LedgerCalendarRevision, Expense, ExpenseOffsetFact, BillSplitInvitation, CsvImportBatch, CsvImportRow):
        columns = {item["name"]: item for item in inspector.get_columns(model.__tablename__)}
        for column in model.__table__.c:
            assert columns[column.name]["nullable"] == column.nullable
            actual_type = str(columns[column.name]["type"].compile(dialect=engine.dialect))
            declared_type = str(column.type.compile(dialect=engine.dialect))
            assert actual_type == postgresql_aliases.get(declared_type, declared_type), (model.__tablename__, column.name)
        assert {item["name"] for item in inspector.get_check_constraints(model.__tablename__)} == {
            item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)
        }
        for constraint in model.__table__.constraints:
            if isinstance(constraint, ForeignKeyConstraint) and constraint.name and "calendar" in constraint.name:
                actual = next(item for item in inspector.get_foreign_keys(model.__tablename__) if item["name"] == constraint.name)
                assert actual["constrained_columns"] == list(constraint.column_keys)
                assert actual["referred_columns"] == ["ledger_id", "revision"]


@pytest.mark.parametrize("currency_state", ["ACTIVE", "EMPTY", "ADOPTION_REQUIRED"])
def test_calendar_adoption_preserves_facts_versions_and_unbound_period_reads(calendar_edge, currency_state):
    _, original = calendar_edge
    _run(command.upgrade, _HEAD)
    _set_currency_state(currency_state)
    with SessionLocal.begin() as db:
        rule = adopt_ledger_calendar(db, ledger_id="calendar-live", timezone_name="Asia/Shanghai")
        assert rule.timezone_name == "Asia/Shanghai"
        assert db.scalar(text("SELECT current_setting('xpj.calendar_adoption', true)")) == ""
    with SessionLocal.begin() as db:
        assert adopt_ledger_calendar(db, ledger_id="calendar-live", timezone_name="UTC").timezone_name == "Asia/Shanghai"
        adopt_ledger_calendar(db, ledger_id="calendar-archived", timezone_name="Asia/Shanghai")
        assert current_calendar(db, ledger_id="calendar-archived").revision == 1
        assert calendar_revision(db, ledger_id="calendar-live", revision=1).basis == "legacy_assumed"
    current = _snapshot()
    assert [row["accounting_date"] for row in current["expenses"]] == [date(2026, 5, 1), date(2026, 5, 1), None]
    assert [row["accounting_date_basis"] for row in current["expenses"]] == [
        "legacy_expense_time", "legacy_confirmed_at", "legacy_unknown"]
    assert all(row["time_precision"] == "unknown" and row["user_local_date"] is None for row in current["expenses"])
    assert current["expense_offset_facts"][0]["time_precision"] == "date_only"
    assert current["expense_offset_facts"][0]["user_local_date"] is None
    assert _without_calendar(current) == original
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM expenses WHERE accounting_date >= '2026-05-01' "
                              "AND accounting_date < '2026-06-01'")) == 2
        assert db.scalar(text("SELECT count(*) FROM ledger_audit_logs WHERE action = 'calendar_adopted'")) == 2
        assert db.scalar(text("SELECT state FROM installation_currency_bindings")) == currency_state
    with pytest.raises(DBAPIError, match="XPJ_CURRENCY_FENCE"), SessionLocal.begin() as db:
        db.execute(text("UPDATE expenses SET note = 'not authorized'"))
    if currency_state == "ACTIVE":
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("UPDATE expenses SET note = 'ordinary currency writer still works'"))
    with pytest.raises(RuntimeError, match="discard adopted" ):
        _run(command.downgrade, _PARENT)


def _proof(db, ledger="calendar-live", *, revision=1, purpose="legacy_adoption"):
    db.execute(text("SELECT set_config('xpj.calendar_adoption', :proof, true)"),
               {"proof": json.dumps({"purpose": purpose, "ledger_id": ledger, "revision": revision})})


def test_calendar_fence_refuses_mixed_writes_foreign_ledgers_and_evidence_rewrites(calendar_edge):
    roots, _ = calendar_edge
    _run(command.upgrade, _HEAD)
    with SessionLocal.begin() as db:
        # Arm the exact pre-materialization state: failures below must reject a
        # mixed write on eligible history, not merely reject a second adoption.
        for ledger, zone in (("calendar-live", "Asia/Shanghai"), ("calendar-archived", "UTC")):
            db.add(LedgerCalendarRevision(ledger_id=ledger, revision=1, timezone_name=zone, basis="legacy_assumed"))
            db.flush()
            db.execute(text("UPDATE ledgers SET calendar_revision = 1 WHERE ledger_id = :ledger"), {"ledger": ledger})
    valid = "calendar_revision = 1, accounting_date = '2026-05-01', time_precision = 'unknown', accounting_date_basis = 'legacy_expense_time'"
    for assignment in ("amount_cents = 9", "status = 'rejected'", "tenant_id = 'calendar-archived'",
                       "row_version = 8", "fact_revision = 2", "updated_at = now()", "expense_time = now()",
                       "user_local_date = '2026-05-01'"):
        with pytest.raises(DBAPIError, match="XPJ_CALENDAR_FENCE"), SessionLocal.begin() as db:
            _proof(db)
            db.execute(text(f"UPDATE expenses SET {valid}, {assignment} WHERE id = :id"), {"id": roots[0]})
    for options in ({"ledger": "calendar-archived"}, {"revision": 2}, {"purpose": "write"}):
        with pytest.raises(DBAPIError, match="XPJ_CALENDAR_FENCE"), SessionLocal.begin() as db:
            _proof(db, **options)
            db.execute(text(f"UPDATE expenses SET {valid} WHERE id = :id"), {"id": roots[0]})
    with pytest.raises(DBAPIError, match="incompatible legacy date"), SessionLocal.begin() as db:
        _proof(db)
        db.execute(text(f"UPDATE expenses SET {valid.replace('2026-05-01', '2026-04-30')} WHERE id = :id"), {"id": roots[0]})
    with pytest.raises(DBAPIError, match="XPJ_CALENDAR_FENCE"), SessionLocal.begin() as db:
        _proof(db)
        db.execute(text("UPDATE expense_offset_facts SET accounting_date = '2026-04-30'"))
    for statement in ("DELETE FROM expenses", "TRUNCATE expenses CASCADE"):
        with pytest.raises(DBAPIError, match="FENCE"), SessionLocal.begin() as db:
            _proof(db)
            db.execute(text(statement))
    for statement in ("UPDATE ledger_calendar_revisions SET timezone_name = 'UTC'",
                      "DELETE FROM ledger_calendar_revisions", "TRUNCATE ledger_calendar_revisions CASCADE"):
        with pytest.raises(DBAPIError, match="append-only"), SessionLocal.begin() as db:
            db.execute(text(statement))
    with pytest.raises(IntegrityError, match="fk_ledgers_calendar_revision"), SessionLocal.begin() as db:
        db.execute(text("UPDATE ledgers SET calendar_revision = 2 WHERE ledger_id = 'calendar-live'"))
    with SessionLocal.begin() as db:
        db.add(LedgerCalendarRevision(ledger_id="calendar-archived", revision=2, timezone_name="UTC", basis="owner_selected"))
    for table in ("expenses", "expense_offset_facts", "csv_import_batches"):
        with pytest.raises(IntegrityError, match=f"fk_{table}_calendar_revision"), SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text(f"UPDATE {table} SET calendar_revision = 2"))
    with SessionLocal.begin() as db:
        _proof(db)
        db.execute(text(f"UPDATE expenses SET {valid} WHERE id = :id"), {"id": roots[0]})
    with pytest.raises(DBAPIError, match="only first adoption"), SessionLocal.begin() as db:
        _proof(db)
        db.execute(text(f"UPDATE expenses SET {valid} WHERE id = :id"), {"id": roots[0]})


def test_calendar_adoption_rolls_back_and_concurrent_attempts_reuse_one_rule(calendar_edge):
    _, original = calendar_edge
    _run(command.upgrade, _HEAD)
    with pytest.raises(RuntimeError, match="injected"), SessionLocal.begin() as db:
        adopt_ledger_calendar(db, ledger_id="calendar-live", timezone_name="Asia/Shanghai")
        raise RuntimeError("injected before commit")
    assert _without_calendar(_snapshot()) == original
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM ledger_calendar_revisions")) == 0
        assert db.scalar(text("SELECT count(*) FROM ledger_audit_logs")) == 0
        assert db.scalar(text("SELECT count(*) FROM expenses WHERE calendar_revision IS NOT NULL OR accounting_date IS NOT NULL")) == 0
    ready = Barrier(2)

    def adopt(zone):
        with SessionLocal.begin() as db:
            # Hold a stale identity-map object across the competing commit.
            ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "calendar-live"))
            assert ledger.calendar_revision is None
            ready.wait(timeout=10)
            rule = adopt_ledger_calendar(db, ledger_id="calendar-live", timezone_name=zone)
            return rule.timezone_name

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(adopt, "Asia/Shanghai")
        second = pool.submit(adopt, "UTC")
        assert first.result(timeout=15) == second.result(timeout=15)
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM ledger_calendar_revisions")) == 1
        assert db.scalar(text("SELECT count(*) FROM ledger_audit_logs")) == 1


def test_calendar_downgrade_cannot_discard_invitation_only_time_evidence(calendar_edge):
    _run(command.upgrade, _HEAD)
    snapshot = {"precision": "date_only", "calendar_revision": 7, "accounting_date": "2026-05-01"}
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        db.execute(text("UPDATE bill_split_invitations SET accounting_time_snapshot = CAST(:snapshot AS jsonb)"),
                   {"snapshot": json.dumps(snapshot)})
    with pytest.raises(RuntimeError, match="frozen invitation time evidence"):
        _run(command.downgrade, _PARENT)
    with engine.connect() as db:
        assert db.scalar(text("SELECT accounting_time_snapshot FROM bill_split_invitations")) == snapshot
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD


@pytest.mark.parametrize("field,value", [
    ("time_input", '{"precision":"date_only","calendar_revision":1,"user_local_date":"2026-05-01"}'),
    ("expense_time_input", "2026-03-08 02:30:00"),
])
def test_calendar_downgrade_cannot_discard_csv_original_time(calendar_edge, field, value):
    _run(command.upgrade, _HEAD)
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        assignment = "CAST(:value AS jsonb)" if field == "time_input" else ":value"
        db.execute(text(f"UPDATE csv_import_rows SET {field} = {assignment}"), {"value": value})
    with pytest.raises(RuntimeError, match="original CSV time evidence"):
        _run(command.downgrade, _PARENT)
    with engine.connect() as db:
        assert db.scalar(text(f"SELECT {field} FROM csv_import_rows")) == (
            json.loads(value) if field == "time_input" else value)
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD
