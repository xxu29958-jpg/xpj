"""PG round-trip of 20260620_0002 (add debts.debt_kind, ADR-0049 §7.0 / 8e-6e).

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


def _debts_columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns("debts")}


def _debts_check_names() -> set[str]:
    return {cc["name"] for cc in inspect(engine).get_check_constraints("debts")}


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
    cols = _debts_columns()
    assert "debt_kind" in cols, "debt_kind missing from debts"
    assert cols["debt_kind"]["nullable"] is False, "debt_kind should be NOT NULL"
    assert "ck_debts_kind_valid" in _debts_check_names(), "missing ck_debts_kind_valid"


def test_add_debt_kind_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()  # the current ORM shape

        _reset_empty_database()
        _run_alembic(command.upgrade, "20260620_0002")
        _run_alembic(command.downgrade, "20260620_0001")
        cols = _debts_columns()
        assert "debt_kind" not in cols  # downgrade drops the column
        assert "ck_debts_kind_valid" not in _debts_check_names()  # and the CHECK

        _run_alembic(command.upgrade, "20260620_0002")
        # Re-added via the migration's hand-written ALTER — assert NOT NULL + CHECK, not
        # just the column name, so a migration↔ORM divergence fails here.
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
