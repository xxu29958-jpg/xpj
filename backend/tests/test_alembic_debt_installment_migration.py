"""PG round-trip of 20260620_0003 (add debts.installment_count / _period_months, ADR-0049 §B).

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

_COLS = ("installment_count", "installment_period_months")
_CHECK = "ck_debts_installment_valid"


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
    for name in _COLS:
        assert name in cols, f"{name} missing from debts"
        # Shape A: both nullable (NULL = no installment schedule).
        assert cols[name]["nullable"] is True, f"{name} should be NULLABLE"
    assert _CHECK in _debts_check_names(), f"missing {_CHECK}"


def test_add_debt_installment_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()  # the current ORM shape

        _reset_empty_database()
        _run_alembic(command.upgrade, "20260620_0003")
        _run_alembic(command.downgrade, "20260620_0002")
        cols = _debts_columns()
        for name in _COLS:
            assert name not in cols  # downgrade drops the columns
        assert _CHECK not in _debts_check_names()  # and the CHECK

        _run_alembic(command.upgrade, "20260620_0003")
        # Re-added via the migration's hand-written ALTER — assert nullability + CHECK, not
        # just the column names, so a migration↔ORM divergence fails here.
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
