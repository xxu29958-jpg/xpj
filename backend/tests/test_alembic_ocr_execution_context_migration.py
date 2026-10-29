"""The shipped generation edge preserves receipts and refuses identity erasure."""

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
from tests.test_alembic_ocr_task_recovery_migration import _original_task

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT, _HEAD = "20261029_0001", "20261029_0002"


def test_shipped_execution_context_preserves_receipts_and_refuses_identity_erasure():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with engine.begin() as db:
            db.execute(text("INSERT INTO background_tasks (public_id, task_type, status, created_at, "
                "input_payload_json, result_summary_json, recovery_history_json) VALUES (:id, 'expense_enrichment', "
                "'completed', CURRENT_TIMESTAMP, :payload, :receipt, :history)"), {"id": str(uuid4()),
                "payload": '{"expense_id":8}', "receipt": '{"outcome":"updated"}',
                "history": '[{"error_code":"orphaned_after_restart"}]'})
        before = _original_task()
        run_database_generation_upgrade(_PARENT, _HEAD)
        assert _original_task() == before
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT execution_context_json, recovery_history_json "
                "FROM background_tasks")).one()) == (None, '[{"error_code":"orphaned_after_restart"}]')
        program = compile_program(Path(__file__).resolve().parents[1])
        step = program["revisions"][-1]
        assert program["target_revision"] == _HEAD and step["postcondition"] == "assert_postcondition"
        module = Path(__file__).resolve().parents[1] / step["module_path"]
        assert hashlib.sha256(module.read_bytes()).hexdigest() == step["module_sha256"]
        run_alembic(command.downgrade, _PARENT)
        assert _original_task() == before
        assert "execution_context_json" not in {item["name"] for item in inspect(engine).get_columns("background_tasks")}
        run_alembic(command.upgrade, _HEAD)
        with engine.begin() as db:
            db.execute(text("UPDATE background_tasks SET execution_context_json=:context"),
                {"context": '{"attempt":1,"configured":{"provider":"rapidocr"}}'})
        with pytest.raises(RuntimeError, match="cannot erase retained OCR execution context"):
            run_alembic(command.downgrade, _PARENT)
        assert _original_task() == before
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == _HEAD
            assert db.scalar(text("SELECT execution_context_json FROM background_tasks")) is not None
    finally:
        reset_schema()
