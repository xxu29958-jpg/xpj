"""PG round-trip of 20260622_0001 (add expenses.draft_request_fingerprint, issue #65 slice 1).

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

_COLUMN = "draft_request_fingerprint"


def _expenses_columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns("expenses")}


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


def _assert_full_shape() -> None:
    cols = _expenses_columns()
    assert _COLUMN in cols, f"{_COLUMN} missing from expenses"
    assert cols[_COLUMN]["nullable"] is True, f"{_COLUMN} should be nullable"
    # Pin the length too, not just presence/nullable — a migration↔ORM type/length
    # drift (e.g. one side String(64), the other String(128)) must fail HERE.
    assert getattr(cols[_COLUMN]["type"], "length", None) == 64, (
        f"{_COLUMN} should be VARCHAR(64)"
    )


def test_add_draft_request_fingerprint_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()  # the current ORM shape

        _reset_empty_database()
        _run_alembic(command.upgrade, "20260622_0001")
        _run_alembic(command.downgrade, "20260620_0003")
        assert _COLUMN not in _expenses_columns()  # downgrade drops the column

        _run_alembic(command.upgrade, "20260622_0001")
        # Re-added via the migration's hand-written ALTER — assert the full shape, not
        # just the name, so a migration↔ORM divergence fails here.
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
