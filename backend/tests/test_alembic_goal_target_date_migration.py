"""PG round-trip of 20260616_0002 (add goals.target_date, ADR-0049 §7.0 / 8e-6c).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries
``target_date``) then ``alembic stamp head``, so the migration body never runs on the
normal path. This drives it directly on PostgreSQL (the prod dialect): create_all → stamp
head → downgrade past 20260616_0002 (drops ``target_date``) → upgrade to head (re-adds it).
Pins the single-step nullable ADD as a faithful, round-tripping transform.

Marked ``real_db`` below because it issues DDL via its own
``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.database import Base, engine
from tests._infra.c07_alembic import reset_public_schema, run_alembic_for_test

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

        _run_alembic(command.stamp, "20260616_0002")
        _run_alembic(command.downgrade, "20260616_0001")
        assert "target_date" not in _goals_columns()  # downgrade drops it

        _run_alembic(command.upgrade, "head")
        assert "target_date" in _goals_columns()  # re-added via the guarded ALTER
    finally:
        _reset_empty_database()
        _drop_alembic_version()
