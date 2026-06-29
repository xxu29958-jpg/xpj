"""PG round-trip of 20260629_0002 budget archive fields."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_REVISION = "20260629_0002"
_PRIOR = "20260629_0001"
_TABLE = "budgets"
_INDEX = "ix_budgets_tenant_archived"


def _columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns(_TABLE)}


def _index_names() -> set[str]:
    return {idx["name"] for idx in inspect(engine).get_indexes(_TABLE)}


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
    cols = _columns()
    assert "row_version" in cols
    assert cols["row_version"]["nullable"] is False
    assert "archived_at" in cols
    assert cols["archived_at"]["nullable"] is True
    assert _INDEX in _index_names()


def test_add_budget_archive_fields_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()

        _run_alembic(command.stamp, _REVISION)
        _run_alembic(command.downgrade, _PRIOR)
        cols = _columns()
        assert "row_version" not in cols
        assert "archived_at" not in cols
        assert _INDEX not in _index_names()

        _run_alembic(command.upgrade, "head")
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
