"""PG round-trip of 20260624_0001 (add expenses ck_expenses_row_version_positive CHECK).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries the
``ck_expenses_row_version_positive`` CHECK) then ``alembic stamp head``, so the migration body
never runs on the normal path — a divergence between the migration's hand-written ADD and the
ORM would ship UNDETECTED by the deployment path. This drives it directly on PostgreSQL (the
prod dialect): create_all → stamp head → downgrade past 20260624_0001 (drops the CHECK) →
upgrade to head (re-adds it), asserting the CHECK is present after each forward leg — so a
dropped / typo'd CHECK predicate fails HERE.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via its own
``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_CHECK = "ck_expenses_row_version_positive"


def _expenses_check_names() -> set[str]:
    return {cc["name"] for cc in inspect(engine).get_check_constraints("expenses")}


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


def test_add_expense_row_version_check_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        assert _CHECK in _expenses_check_names()  # the current ORM shape

        _run_alembic(command.stamp, "20260624_0001")
        _run_alembic(command.downgrade, "20260622_0001")
        assert _CHECK not in _expenses_check_names()  # downgrade drops the CHECK

        _run_alembic(command.upgrade, "head")
        # Re-added via the migration's hand-written ALTER — assert the CHECK is back, so a
        # migration↔ORM predicate divergence fails here.
        assert _CHECK in _expenses_check_names()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
