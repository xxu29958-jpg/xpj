"""Real PostgreSQL edge: preserve old tasks and refuse erasing original execution input."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import engine
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db
_PARENT = "20260906_0002"
_HEAD = "20260907_0001"


def _run(action, revision):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    run_alembic_for_test(engine, config, action, revision)


def test_task_input_migration_preserves_old_tasks_and_refuses_erasure():
    reset_public_schema(engine)
    try:
        _run(command.upgrade, _PARENT)
        with engine.begin() as db:
            task_id = db.execute(text(
                "INSERT INTO background_tasks (public_id, task_type, status, created_at, result_summary_json) "
                "VALUES (:public_id, 'csv_import', 'completed', CURRENT_TIMESTAMP, :result) RETURNING id"
            ), {"public_id": str(uuid4()), "result": '{"rows_imported":7}'}).scalar_one()
        _run(command.upgrade, _HEAD)
        column = next(item for item in inspect(engine).get_columns("background_tasks") if item["name"] == "input_payload_json")
        assert column["nullable"] is True
        with engine.connect() as db:
            old = db.execute(text(
                "SELECT status, result_summary_json, input_payload_json FROM background_tasks WHERE id = :id"
            ), {"id": task_id}).one()
            assert tuple(old) == ("completed", '{"rows_imported":7}', None)
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
        _run(command.downgrade, _PARENT)
        assert "input_payload_json" not in {item["name"] for item in inspect(engine).get_columns("background_tasks")}
        _run(command.upgrade, _HEAD)
        original_input = '{"expense_id":8,"expected_row_version":3,"tenant_id":"owner","timezone_name":"UTC"}'
        with engine.begin() as db:
            db.execute(text("UPDATE background_tasks SET input_payload_json = :payload WHERE id = :id"),
                {"id": task_id, "payload": original_input})
        with pytest.raises(RuntimeError, match="original task input exists"):
            _run(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert db.scalar(text("SELECT input_payload_json FROM background_tasks WHERE id = :id"), {"id": task_id}) == original_input
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) == _HEAD
    finally:
        reset_public_schema(engine)
