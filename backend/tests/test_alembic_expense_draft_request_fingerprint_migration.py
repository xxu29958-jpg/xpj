"""PG round-trip of 20260622_0001 (add expenses.draft_request_fingerprint, issue #65 slice 1).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries
``draft_request_fingerprint``) then ``alembic stamp head``, so the migration body never runs
on the normal path — a divergence between the migration's hand-written ADD and the ORM would
ship UNDETECTED by the deployment path. This drives it directly on PostgreSQL (the prod
dialect): create_all → stamp head → downgrade past 20260622_0001 (drops the column) → upgrade
to head (re-adds it), asserting the column's full shape (present + nullable) on both legs.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via its own
``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_COLUMN = "draft_request_fingerprint"


def _expenses_columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns("expenses")}


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
    cols = _expenses_columns()
    assert _COLUMN in cols, f"{_COLUMN} missing from expenses"
    assert cols[_COLUMN]["nullable"] is True, f"{_COLUMN} should be nullable"


def test_add_draft_request_fingerprint_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()  # the current ORM shape

        _run_alembic(command.stamp, "20260622_0001")
        _run_alembic(command.downgrade, "20260620_0003")
        assert _COLUMN not in _expenses_columns()  # downgrade drops the column

        _run_alembic(command.upgrade, "head")
        # Re-added via the migration's hand-written ALTER — assert the full shape, not
        # just the name, so a migration↔ORM divergence fails here.
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
