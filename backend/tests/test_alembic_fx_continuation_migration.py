"""Real PostgreSQL preserves dated quotes and original task evidence at the FX edge."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, engine
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260909_0005"
_HEAD = "20260912_0001"


def _run(action, revision):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    run_alembic_for_test(engine, config, action, revision)


def _seed_parent():
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        account_id = db.scalar(text(
            "INSERT INTO accounts (public_id, display_name, created_at) "
            "VALUES (:public_id, 'FX migration owner', CURRENT_TIMESTAMP) RETURNING id"
        ), {"public_id": str(uuid4())})
        expense_ids = {}
        for ledger in ("fx-owner", "fx-other"):
            db.execute(text(
                "INSERT INTO ledgers (ledger_id, name, owner_account_id, created_at) "
                "VALUES (:ledger, :ledger, :account, CURRENT_TIMESTAMP)"
            ), {"ledger": ledger, "account": account_id})
            expense_ids[ledger] = db.scalar(text(
                "INSERT INTO expenses (public_id, tenant_id, home_currency_code, original_currency_code, "
                "original_amount_minor, fx_status, merchant, category, source, duplicate_status, status, "
                "expense_time, created_at, updated_at) VALUES (:public_id, :ledger, 'CNY', 'USD', 1200, "
                "'pending', 'Historical train', '交通', 'CSV导入', 'none', 'pending', "
                "'2026-04-04T09:00:00Z', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"
            ), {"public_id": str(uuid4()), "ledger": ledger})
        db.execute(text(
            "INSERT INTO fx_rates (public_id, source, home_currency_code, currency_code, rate_date, "
            "rate_to_home, provider_base_currency, provider_rate, fetched_at, created_at, updated_at) "
            "VALUES (:public_id, 'ecb', 'CNY', 'USD', '2026-04-02', 7.25000000, 'EUR', 1.08000000, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"public_id": str(uuid4())})
        owner_id, other_id = expense_ids["fx-owner"], expense_ids["fx-other"]
        original = {"tenant_id": "fx-owner", "expense_id": owner_id, "expected_row_version": 1, "timezone_name": "UTC"}
        cases = [
            ("fx-owner", "expense_enrichment", json.dumps(original), owner_id),
            ("fx-other", "expense_enrichment", json.dumps({**original, "tenant_id": "fx-other", "expense_id": other_id}), other_id),
            ("fx-owner", "expense_enrichment", None, None),
            ("fx-owner", "expense_enrichment", "{broken-json", None),
            ("fx-owner", "expense_enrichment", "[]", None),
            ("fx-owner", "expense_enrichment", json.dumps({**original, "expense_id": True}), None),
            ("fx-owner", "expense_enrichment", json.dumps({**original, "expense_id": str(owner_id)}), None),
            ("fx-owner", "expense_enrichment", json.dumps({**original, "expense_id": float(owner_id)}), None),
            ("fx-owner", "expense_enrichment", json.dumps({**original, "tenant_id": "fx-other"}), None),
            ("fx-owner", "expense_enrichment", json.dumps({**original, "expense_id": other_id}), None),
            ("fx-owner", "expense_enrichment", json.dumps({**original, "expense_id": 99999999}), None),
            ("fx-owner", "csv_import", json.dumps(original), None),
        ]
        expected_sources = {}
        for tenant, task_type, payload, source in cases:
            task_id = db.scalar(text(
                "INSERT INTO background_tasks (public_id, tenant_id, task_type, status, input_payload_json, "
                "result_summary_json, created_at) VALUES (:public_id, :tenant, :task_type, 'failed', "
                ":payload, :result, CURRENT_TIMESTAMP) RETURNING id"
            ), {"public_id": str(uuid4()), "tenant": tenant, "task_type": task_type,
                "payload": payload, "result": '{"outcome":"no_result"}'})
            expected_sources[task_id] = source
    return owner_id, expected_sources


def _snapshot():
    with engine.connect() as db:
        return {
            table: [dict(row) for row in db.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
            for table in ("fx_rates", "background_tasks", "expenses")
        }


def _assert_preserved(original, expected_sources):
    current = _snapshot()
    for rate in current["fx_rates"]:
        assert rate.pop("verified_through") is None
    for task in current["background_tasks"]:
        assert task.pop("source_expense_id") == expected_sources[task["id"]]
    assert current == original
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == _HEAD
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD


def test_fx_continuation_migration_preserves_evidence_and_guards_downgrade():
    reset_public_schema(engine)
    try:
        _run(command.upgrade, _PARENT)
        owner_id, expected_sources = _seed_parent()
        original = _snapshot()
        _run(command.upgrade, _HEAD)
        _assert_preserved(original, expected_sources)
        inspector = inspect(engine)
        assert next(c for c in inspector.get_columns("fx_rates") if c["name"] == "verified_through")["nullable"]
        assert next(c for c in inspector.get_columns("background_tasks") if c["name"] == "source_expense_id")["nullable"]
        assert any(i["column_names"] == ["source_expense_id"] for i in inspector.get_indexes("background_tasks"))
        source_fk = next(f for f in inspector.get_foreign_keys("background_tasks") if f["constrained_columns"] == ["source_expense_id"])
        assert (source_fk["referred_table"], source_fk["referred_columns"], source_fk["options"]["ondelete"]) == ("expenses", ["id"], "SET NULL")
        with pytest.raises(IntegrityError, match="ck_fx_rates_coverage_date"), engine.begin() as db:
            db.execute(text("UPDATE fx_rates SET verified_through = '2026-04-01'"))

        # Legacy enrichment still has its original input; this edge alone can be reversed.
        _run(command.downgrade, _PARENT)
        assert "verified_through" not in {c["name"] for c in inspect(engine).get_columns("fx_rates")}
        assert "source_expense_id" not in {c["name"] for c in inspect(engine).get_columns("background_tasks")}
        assert _snapshot() == original
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == _PARENT
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _PARENT
        _run(command.upgrade, _HEAD)
        _assert_preserved(original, expected_sources)

        # Even a failed dated-FX task still owns a continuation that the old code cannot read.
        with engine.begin() as db:
            db.execute(text(
                "INSERT INTO background_tasks (public_id, tenant_id, task_type, source_expense_id, status, "
                "input_payload_json, error_code, created_at) VALUES (:public_id, 'fx-owner', 'expense_fx', "
                ":expense_id, 'failed', :payload, 'fx_unavailable', CURRENT_TIMESTAMP)"
            ), {"public_id": str(uuid4()), "expense_id": owner_id,
                "payload": json.dumps({"tenant_id": "fx-owner", "expense_id": owner_id, "expected_row_version": 1})})
        before_downgrade = _snapshot()
        with pytest.raises(RuntimeError, match="cannot remove original foreign-bill task continuation"):
            _run(command.downgrade, _PARENT)
        assert _snapshot() == before_downgrade
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == _HEAD
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD

        # Removing an original leaves the durable task and input, but no dangling navigation.
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("DELETE FROM expenses WHERE id = :id"), {"id": owner_id})
        after_delete = _snapshot()["background_tasks"]
        expected_tasks = before_downgrade["background_tasks"]
        for task in expected_tasks:
            if task["source_expense_id"] == owner_id:
                task["source_expense_id"] = None
        assert after_delete == expected_tasks
    finally:
        reset_public_schema(engine)
