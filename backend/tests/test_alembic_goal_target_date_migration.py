"""PG round-trip of 20260616_0002 (add goals.target_date, ADR-0049 §7.0 / 8e-6c).

Check current ORM shape independently, then round-trip the frozen migration
on its actual PostgreSQL schema. Never stamp a current schema as a historical one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.database import engine
from app.database_model_registry import Base
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db


def _goals_columns() -> set[str]:
    return {col["name"] for col in inspect(engine).get_columns("goals")}


def _reset_empty_database() -> None:
    reset_public_schema(engine)


def _drop_alembic_version() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _alembic_cfg():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


def _run_alembic(action, *args) -> None:
    run_alembic_for_test(engine, _alembic_cfg(), action, *args)


def test_add_goal_target_date_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        assert "target_date" in _goals_columns()  # the current models carry it

        _reset_empty_database()
        _run_alembic(command.upgrade, "20260616_0002")
        _run_alembic(command.downgrade, "20260616_0001")
        assert "target_date" not in _goals_columns()  # downgrade drops it

        _run_alembic(command.upgrade, "20260616_0002")
        assert "target_date" in _goals_columns()  # re-added via the guarded ALTER
    finally:
        _reset_empty_database()
        _drop_alembic_version()
