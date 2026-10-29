"""Ship the recovery edge through the existing generation runner without erasing old receipts."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text

from app.database import engine
from scripts.build_database_generation_program import compile_program
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.c07_money_protocol_probe import run_database_generation_upgrade

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT, _HEAD = "20261028_0001", "20261029_0001"


def _original_task():
    with engine.connect() as db:
        return list(db.execute(text("SELECT id, public_id, task_type, status, input_payload_json, "
            "result_summary_json, created_at FROM background_tasks ORDER BY id")).mappings())


def test_shipped_recovery_migration_preserves_old_receipts_and_refuses_attempt_erasure():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with engine.begin() as db:
            db.execute(text("INSERT INTO background_tasks (public_id, task_type, status, created_at, "
                "input_payload_json, result_summary_json) VALUES (:public_id, 'expense_enrichment', 'completed', "
                "CURRENT_TIMESTAMP, :payload, :receipt)"), {"public_id": str(uuid4()),
                "payload": '{"expense_id":8,"tenant_id":"owner","expected_row_version":1}',
                "receipt": '{"outcome":"updated","row_version":2}'})
        before = _original_task()
        run_database_generation_upgrade(_PARENT, _HEAD)
        assert _original_task() == before
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT recovery_attempts, recovery_after, recovery_history_json "
                "FROM background_tasks")).one()) == (0, None, "[]")
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == _HEAD
        program = compile_program(Path(__file__).resolve().parents[1])
        step = next(item for item in program["revisions"] if item["revision"] == _HEAD)
        assert step["postcondition"] == "assert_postcondition"
        module = Path(__file__).resolve().parents[1] / step["module_path"]
        assert hashlib.sha256(module.read_bytes()).hexdigest() == step["module_sha256"]
        run_alembic(command.downgrade, _PARENT)
        assert _original_task() == before
        assert "recovery_attempts" not in {item["name"] for item in inspect(engine).get_columns("background_tasks")}
        run_alembic(command.upgrade, _HEAD)
        with engine.begin() as db:
            db.execute(text("UPDATE background_tasks SET recovery_attempts=1, "
                "recovery_history_json=:history"), {"history": '[{"error_code":"ocr_timeout"}]'})
        with pytest.raises(RuntimeError, match="cannot erase retained OCR recovery attempts"):
            run_alembic(command.downgrade, _PARENT)
        assert _original_task() == before
        with engine.connect() as db:
            assert db.scalar(text("SELECT recovery_attempts FROM background_tasks")) == 1
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == _HEAD
    finally:
        reset_schema()
