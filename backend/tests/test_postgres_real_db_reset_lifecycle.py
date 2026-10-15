from __future__ import annotations

from threading import Event

import pytest
from sqlalchemy import event, text

from app.database import SessionLocal, engine
from app.database._lifecycle import load_alembic_context
from app.models import DatasetAuthorityRecord
from app.services import background_task_executor
from app.services.background_task_registry import TaskHandlerRegistry
from tests._infra import db as test_db


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_clear_then_full_reset_restores_schema_migration_seed_and_files() -> None:
    runtime_path = test_db._DATA_RUNTIME_ROOT / test_db.TEST_RUN_ID
    runtime_path.mkdir(parents=True, exist_ok=True)
    (runtime_path / "sentinel.txt").write_text("owned test data", encoding="utf-8")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE lifecycle_teardown_sentinel (id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO lifecycle_teardown_sentinel (id) VALUES (1)"))
        connection.execute(text("DROP TABLE alembic_version"))

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.alembic_version')")) is None

    entered, release, finished = Event(), Event(), Event()

    def read_before_teardown(_task_id, _payload, _registry):
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT id FROM lifecycle_teardown_sentinel")) == 1
            entered.set()
            release.wait(2)
        finished.set()

    def bound_schema_wait(_connection, cursor, statement, _parameters, _context, _many):
        if statement.startswith("DROP SCHEMA"):
            cursor.execute("SET LOCAL lock_timeout = '150ms'")

    # A real executor still owns a live PostgreSQL reader when reset starts.
    # Reset must join it before DDL, not race it or leave it querying the next test.
    event.listen(engine, "before_cursor_execute", bound_schema_wait)
    try:
        background_task_executor.submit_task(0, {}, registry=TaskHandlerRegistry(), runner=read_before_teardown)
        assert entered.wait(5)
        test_db.clear_db_state()
        assert finished.is_set()
    finally:
        release.set()
        background_task_executor.shutdown_executor(wait=True)
        event.remove(engine, "before_cursor_execute", bound_schema_wait)

    assert not runtime_path.exists()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.lifecycle_teardown_sentinel')")) is None
        assert connection.scalar(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        ) == 0

    test_db.reset_db_state()

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            load_alembic_context().head_revision
        )
        assert connection.scalar(text("SELECT to_regclass('public.lifecycle_teardown_sentinel')")) is None
    with SessionLocal() as db:
        assert db.get(DatasetAuthorityRecord, 1) is not None
