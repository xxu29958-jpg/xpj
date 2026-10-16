"""PG round-trip of 20260624_0001 (add expenses ck_expenses_row_version_positive CHECK).

Check current ORM shape independently, then round-trip the frozen migration
on its actual PostgreSQL schema. Never stamp a current schema as a historical one.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.database import engine
from app.database_model_registry import Base
from tests._infra.alembic_runtime import alembic_config_for_test, reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db

_CHECK = "ck_expenses_row_version_positive"


def _expenses_check_names() -> set[str]:
    return {cc["name"] for cc in inspect(engine).get_check_constraints("expenses")}


def _reset_empty_database() -> None:
    reset_public_schema(engine)


def _drop_alembic_version() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _run_alembic(action, *args) -> None:
    run_alembic_for_test(engine, alembic_config_for_test(), action, *args)


def test_add_expense_row_version_check_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        assert _CHECK in _expenses_check_names()  # the current ORM shape

        _reset_empty_database()
        _run_alembic(command.upgrade, "20260624_0001")
        _run_alembic(command.downgrade, "20260622_0001")
        assert _CHECK not in _expenses_check_names()  # downgrade drops the CHECK

        _run_alembic(command.upgrade, "20260624_0001")
        # Re-added via the migration's hand-written ALTER — assert the CHECK is back, so a
        # migration↔ORM predicate divergence fails here.
        assert _CHECK in _expenses_check_names()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
