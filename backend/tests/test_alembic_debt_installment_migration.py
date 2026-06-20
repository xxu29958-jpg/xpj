"""PG round-trip of 20260620_0003 (add debts.installment_count / _period_months, ADR-0049 §B).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries the two
installment columns + the ``ck_debts_installment_valid`` CHECK) then ``alembic stamp head``, so
the migration body never runs on the normal path — a divergence between the migration's
hand-written ADD and the ORM would ship UNDETECTED by the deployment path. This drives it
directly on PostgreSQL (the prod dialect): create_all → stamp head → downgrade past 20260620_0003
(drops the CHECK + both columns) → upgrade to head (re-adds them), then asserts both columns are
NULLABLE and the CHECK is back — not just that the names exist, so a flipped nullability / a
typo'd CHECK in the migration fails HERE.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via its own
``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_COLS = ("installment_count", "installment_period_months")
_CHECK = "ck_debts_installment_valid"


def _debts_columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns("debts")}


def _debts_check_names() -> set[str]:
    return {cc["name"] for cc in inspect(engine).get_check_constraints("debts")}


def _reset_empty_database() -> None:
    Base.metadata.drop_all(bind=engine)


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
    cfg = _alembic_cfg()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        action(cfg, *args)


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

        _run_alembic(command.stamp, "20260620_0003")
        _run_alembic(command.downgrade, "20260620_0002")
        cols = _debts_columns()
        for name in _COLS:
            assert name not in cols  # downgrade drops the columns
        assert _CHECK not in _debts_check_names()  # and the CHECK

        _run_alembic(command.upgrade, "head")
        # Re-added via the migration's hand-written ALTER — assert nullability + CHECK, not
        # just the column names, so a migration↔ORM divergence fails here.
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
