"""Real PostgreSQL preserves CSV history and enforces ledger-local event receipts."""

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, UniqueConstraint, insert, inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, engine
from app.models import CsvImportEvent, CsvImportRow
from app.money_contract import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260912_0001"
_HEAD = "20260919_0001"
_EVENT_COLUMNS = (
    "entry_kind", "offset_kind", "source_event_public_id", "source_root_public_id",
    "accounting_date", "stream_amount_cents", "lineage_status", "lineage_home_net_cents", "event_input", "review_reason",
)
_ROW_INSERT = """
    INSERT INTO csv_import_rows (tenant_id, batch_id, line_number, status, amount_cents,
        home_currency_code, original_currency_code, original_amount_minor, exchange_rate_to_cny,
        exchange_rate_date, exchange_rate_source, merchant, category, source, expense_id,
        error_code, error_message, created_at, updated_at)
    VALUES (:tenant, :batch, :line, :status, 1800, 'CNY', 'USD', 250, 7.2,
        '2026-04-04', 'manual', 'Historical train', '交通', 'CSV导入', :expense,
        :error_code, :error_message, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id
"""


def _run(action, revision):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    run_alembic_for_test(engine, config, action, revision)


def _insert_batch(db, tenant):
    return db.scalar(text(
        "INSERT INTO csv_import_batches (public_id, tenant_id, file_name, status, total_rows, "
        "valid_rows, error_rows, applied_rows, inserted_count, created_at, updated_at) "
        "VALUES (:public_id, :tenant, 'history.csv', 'parsed_with_errors', 3, 2, 1, 1, 1, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"
    ), {"public_id": str(uuid4()), "tenant": tenant})


def _seed_parent():
    records = {}
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        account = db.scalar(text(
            "INSERT INTO accounts (public_id, display_name, created_at) "
            "VALUES (:public_id, 'CSV migration owner', CURRENT_TIMESTAMP) RETURNING id"
        ), {"public_id": str(uuid4())})
        for tenant in ("csv-owner", "csv-other"):
            db.execute(text(
                "INSERT INTO ledgers (ledger_id, name, owner_account_id, created_at) "
                "VALUES (:tenant, :tenant, :account, CURRENT_TIMESTAMP)"
            ), {"tenant": tenant, "account": account})
            expense = db.scalar(text(
                "INSERT INTO expenses (public_id, tenant_id, amount_cents, home_currency_code, "
                "original_currency_code, original_amount_minor, exchange_rate_to_cny, exchange_rate_date, "
                "exchange_rate_source, fx_status, merchant, category, source, duplicate_status, status, "
                "expense_time, confirmed_at, created_at, updated_at, row_version, fact_revision) "
                "VALUES (:public_id, :tenant, 1800, 'CNY', 'USD', 250, 7.2, '2026-04-04', 'manual', "
                "'ready', 'Historical train', '交通', 'CSV导入', 'none', 'confirmed', "
                "'2026-04-04T09:00:00Z', '2026-04-05T10:00:00Z', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 7, 1) "
                "RETURNING id"
            ), {"public_id": str(uuid4()), "tenant": tenant})
            offset = db.scalar(text(
                "INSERT INTO expense_offset_facts (public_id, tenant_id, expense_id, kind, status, "
                "original_currency_code, original_amount_minor, home_currency_code, amount_cents, "
                "exchange_rate_to_cny, exchange_rate_date, exchange_rate_source, accounting_date, "
                "category, reason, created_actor_account_id, created_at, updated_at) "
                "VALUES (:public_id, :tenant, :expense, 'refund', 'active', 'USD', 50, 'CNY', 360, "
                "7.2, '2026-04-04', 'manual', '2026-04-06', '交通', 'Partial refund', :account, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"
            ), {"public_id": str(uuid4()), "tenant": tenant, "expense": expense, "account": account})
            db.execute(text(
                "INSERT INTO expense_revisions (public_id, tenant_id, expense_id, revision_number, "
                "change_kind, reason, idempotency_key, actor_account_id, changed_fields, after_snapshot, "
                "resulting_row_version, created_at) SELECT :public_id, tenant_id, id, 1, 'confirmed', "
                "'Original purchase', :request_key, :account, '[]'::json, to_jsonb(expenses)::json, "
                "row_version, CURRENT_TIMESTAMP FROM expenses WHERE id = :expense"
            ), {"public_id": str(uuid4()), "request_key": str(uuid4()), "account": account, "expense": expense})
            db.execute(text(
                "INSERT INTO expense_offset_revisions (public_id, tenant_id, expense_id, offset_id, "
                "revision_number, change_kind, reason, idempotency_key, actor_account_id, after_snapshot, "
                "resulting_row_version, created_at) SELECT :public_id, tenant_id, expense_id, id, 1, "
                "'created', reason, :request_key, :account, to_jsonb(expense_offset_facts)::json, "
                "row_version, CURRENT_TIMESTAMP FROM expense_offset_facts WHERE id = :offset"
            ), {"public_id": str(uuid4()), "request_key": str(uuid4()), "account": account, "offset": offset})
            batch = _insert_batch(db, tenant)
            rows = {}
            for line, status in enumerate(("valid", "error", "applied"), start=2):
                rows[status] = db.scalar(text(_ROW_INSERT), {
                    "tenant": tenant, "batch": batch, "line": line, "status": status,
                    "expense": expense if status == "applied" else None,
                    "error_code": "invalid_date" if status == "error" else None,
                    "error_message": "Correct the original date" if status == "error" else None,
                })
            records[tenant] = {"batch": batch, "expense": expense, "offset": offset, "rows": rows}
    return records


def _snapshot(*, events=False):
    tables = (
        "accounts", "ledgers", "expenses", "expense_revisions", "expense_offset_facts",
        "expense_offset_revisions", "csv_import_batches", "csv_import_rows",
    ) + (("csv_import_events",) if events else ())
    with engine.connect() as db:
        return {
            table: [dict(row) for row in db.execute(text(
                f"SELECT * FROM {table} ORDER BY {'ledger_id' if table == 'ledgers' else 'id'}"
            )).mappings()]
            for table in tables
        }


def _assert_authority(revision):
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == revision


@pytest.fixture
def csv_event_edge():
    reset_public_schema(engine)
    try:
        _run(command.upgrade, _PARENT)
        records = _seed_parent()
        yield records, _snapshot()
    finally:
        reset_public_schema(engine)


def _assert_upgraded_history(original):
    current = _snapshot(events=True)
    assert current.pop("csv_import_events") == []
    for row in current["csv_import_rows"]:
        assert row.pop("entry_kind") == "expense"
        for column in _EVENT_COLUMNS[1:]:
            assert row.pop(column) is None
    assert current == original
    _assert_authority(_HEAD)


def _assert_schema_matches_metadata():
    inspector = inspect(engine)
    for table, selected in (
        (CsvImportRow.__table__, _EVENT_COLUMNS), (CsvImportEvent.__table__, tuple(CsvImportEvent.__table__.c.keys())),
    ):
        reflected = {column["name"]: column for column in inspector.get_columns(table.name)}
        for name in selected:
            expected = table.c[name]
            assert reflected[name]["nullable"] == expected.nullable
            assert str(reflected[name]["type"].compile(dialect=engine.dialect)) == str(expected.type.compile(dialect=engine.dialect))
        assert {item["name"] for item in inspector.get_check_constraints(table.name)} == {
            item.name for item in table.constraints if isinstance(item, CheckConstraint)
        }
        assert {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)} == {
            tuple(column.name for column in item.columns) for item in table.constraints if isinstance(item, UniqueConstraint)
        }
    assert any(
        item["name"] == "ix_csv_import_rows_source_event"
        and item["column_names"] == ["tenant_id", "entry_kind", "source_event_public_id"]
        and not item["unique"]
        for item in inspector.get_indexes("csv_import_rows")
    )


def _new_row(db, record, *, tenant="csv-owner", line=20, **values):
    return db.scalar(insert(CsvImportRow).values(
        tenant_id=tenant, batch_id=record["batch"], line_number=line,
        **{"status": "valid", "home_currency_code": "CNY", "original_currency_code": "CNY", **values},
    ).returning(CsvImportRow.id))


def _new_event(db, *, source_row, source_id=None, tenant="csv-owner", **values):
    return db.scalar(insert(CsvImportEvent).values(
        tenant_id=tenant, source_row_id=source_row, source_event_public_id=source_id or str(uuid4()),
        **{"entry_kind": "expense", **values},
    ).returning(CsvImportEvent.id))


def _assert_staged_projection_bounds(owner):
    # Unknown ordinary/error inputs stay NULL. Signed exported projections can
    # exceed a single fact's limit, but must fit the supported aggregate range.
    accepted = (None, -MONEY_AGGREGATE_MAX, -MONEY_MINOR_MAX - 1, 0, MONEY_MINOR_MAX + 1, MONEY_AGGREGATE_MAX)
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        row_ids = [
            _new_row(db, owner, line=line, stream_amount_cents=value, lineage_home_net_cents=value)
            for line, value in enumerate(accepted, start=100)
        ]
    with engine.connect() as db:
        actual = db.execute(text(
            "SELECT stream_amount_cents, lineage_home_net_cents FROM csv_import_rows "
            "WHERE id = ANY(:ids) ORDER BY line_number"
        ), {"ids": row_ids}).all()
    assert actual == [(value, value) for value in accepted]
    for column in ("stream_amount_cents", "lineage_home_net_cents"):
        for invalid in (-MONEY_AGGREGATE_MAX - 1, MONEY_AGGREGATE_MAX + 1):
            with pytest.raises(IntegrityError, match=f"ck_csv_import_rows_{column}_projection_bounds"), SessionLocal.begin() as db:
                activate_test_currency_authority(db, "CNY")
                _new_row(db, owner, line=200, **{column: invalid})


def test_csv_event_migration_preserves_history_round_trips_and_enforces_ledger_receipts(csv_event_edge):
    records, original = csv_event_edge
    owner, other = records["csv-owner"], records["csv-other"]
    _run(command.upgrade, _HEAD)
    _assert_upgraded_history(original)
    _assert_schema_matches_metadata()

    # Ordinary saved rows and existing financial facts do not make this edge irreversible.
    _run(command.downgrade, _PARENT)
    assert _snapshot() == original
    assert "csv_import_events" not in inspect(engine).get_table_names()
    assert not set(_EVENT_COLUMNS) & {column["name"] for column in inspect(engine).get_columns("csv_import_rows")}
    _assert_authority(_PARENT)
    _run(command.upgrade, _HEAD)
    _assert_upgraded_history(original)
    _assert_staged_projection_bounds(owner)

    source_id = str(uuid4())
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        rows = {
            status: _new_row(db, owner, line=line, status=status, source_event_public_id=source_id)
            for line, status in enumerate(("review", "matched", "conflict"), start=20)
        }
        other_row = _new_row(db, other, tenant="csv-other", source_event_public_id=source_id)
        second_batch = {"batch": _insert_batch(db, "csv-owner")}
        repeated_row = _new_row(db, second_batch, source_event_public_id=source_id)
        event_id = _new_event(db, source_row=rows["matched"], source_id=source_id, expense_id=owner["expense"])
        # Identity is (chosen ledger, source kind, source UUID), not UUID alone.
        _new_event(db, tenant="csv-other", source_row=other_row, source_id=source_id, expense_id=other["expense"])
        _new_event(db, source_row=rows["review"], source_id=source_id, entry_kind="offset",
                   expense_id=owner["expense"], offset_id=owner["offset"])

    with pytest.raises(IntegrityError, match="uq_csv_import_events_source"), SessionLocal.begin() as db:
        _new_event(db, source_row=repeated_row, source_id=source_id, expense_id=owner["expense"])
    with engine.connect() as db:
        assert db.execute(text(
            "SELECT source_row_id, expense_id FROM csv_import_events WHERE id = :id"
        ), {"id": event_id}).one() == (rows["matched"], owner["expense"])

    # A manually resolved root can precede its actual source row. It records no purchase.
    root_source_id = str(uuid4())
    with SessionLocal.begin() as db:
        root_event = _new_event(db, source_row=None, source_id=root_source_id, expense_id=owner["expense"])
    with engine.connect() as db:
        assert db.execute(text(
            "SELECT source_row_id, expense_id, offset_id FROM csv_import_events WHERE id = :id"
        ), {"id": root_event}).one() == (None, owner["expense"], None)
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        source_row = _new_row(db, owner, line=23, source_event_public_id=root_source_id)
        db.execute(text("UPDATE csv_import_events SET source_row_id = :row WHERE id = :id"),
                   {"row": source_row, "id": root_event})
    with engine.connect() as db:
        assert db.scalar(text("SELECT source_row_id FROM csv_import_events WHERE id = :id"), {"id": root_event}) == source_row

    for constraint, values in (
        ("fk_csv_import_events_source_row", {"source_row": other_row}),
        ("fk_csv_import_events_expense", {"source_row": rows["review"], "expense_id": other["expense"]}),
        ("fk_csv_import_events_expense", {"source_row": None, "expense_id": other["expense"]}),
        ("fk_csv_import_events_offset", {"source_row": rows["review"], "entry_kind": "offset",
                                          "expense_id": owner["expense"], "offset_id": other["offset"]}),
        ("ck_csv_import_events_kind", {"source_row": rows["review"], "entry_kind": "unknown"}),
        ("ck_csv_import_events_source", {"source_row": None}),
        ("ck_csv_import_events_source", {"source_row": None, "entry_kind": "offset", "expense_id": owner["expense"]}),
        ("ck_csv_import_events_result", {"source_row": rows["review"], "offset_id": owner["offset"]}),
        ("ck_csv_import_events_result", {"source_row": rows["review"], "entry_kind": "offset", "offset_id": owner["offset"]}),
    ):
        with pytest.raises(IntegrityError, match=constraint), SessionLocal.begin() as db:
            _new_event(db, **values)
    for constraint, values in (
        ("uq_csv_import_rows_tenant_expense_id", {"expense_id": owner["expense"]}),
        ("ck_csv_import_rows_status_valid", {"status": "silently_confirmed"}),
    ):
        with pytest.raises(IntegrityError, match=constraint), SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            _new_row(db, owner, line=99, **values)
    current = _snapshot()
    for table in ("accounts", "ledgers", "expenses", "expense_revisions", "expense_offset_facts", "expense_offset_revisions"):
        assert current[table] == original[table]


def test_csv_event_downgrade_keeps_native_input_review_and_mapping(csv_event_edge):
    records, original = csv_event_edge
    owner = records["csv-owner"]
    _run(command.upgrade, _HEAD)
    source_id = str(uuid4())
    cases = (
        {"source_event_public_id": source_id, "source_root_public_id": source_id,
         "accounting_date": date(2026, 4, 4), "stream_amount_cents": 1800,
         "lineage_status": "active", "lineage_home_net_cents": 1800,
         "event_input": {"entry_kind": "expense", "exchange_rate_source": "manual"},
         "review_reason": "I chose to bring in only the gross purchase draft."},
        {"entry_kind": "offset", "offset_kind": "reversal", "status": "review",
         "stream_amount_cents": 0, "lineage_home_net_cents": 0,
         "event_input": {"entry_kind": "offset", "offset_kind": "reversal"}},
        {"status": "error", "event_input": {"entry_kind": "unrecognized-export-kind"}},
        {"status": "error", "entry_kind": "unrecognized-export-kind"},
        {"review_reason": "I accepted the incomplete source relationship."},
        {"status": "review"}, {"status": "matched"}, {"status": "conflict"},
    )
    for values in cases:
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            row_id = _new_row(db, owner, **values)
        before = _snapshot(events=True)
        with pytest.raises(RuntimeError, match="cannot erase native CSV financial-event continuation"):
            _run(command.downgrade, _PARENT)
        assert _snapshot(events=True) == before
        _assert_authority(_HEAD)
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("DELETE FROM csv_import_rows WHERE id = :id"), {"id": row_id})

    # A resolved root mapping owns continuation even before its real source row arrives.
    with SessionLocal.begin() as db:
        event_id = _new_event(db, source_row=None, expense_id=owner["expense"])
    before = _snapshot(events=True)
    with pytest.raises(RuntimeError, match="cannot erase native CSV financial-event continuation"):
        _run(command.downgrade, _PARENT)
    assert _snapshot(events=True) == before
    _assert_authority(_HEAD)
    _assert_schema_matches_metadata()
    with engine.begin() as db:
        db.execute(text("DELETE FROM csv_import_events WHERE id = :id"), {"id": event_id})
    _run(command.downgrade, _PARENT)
    assert _snapshot() == original
    _assert_authority(_PARENT)
