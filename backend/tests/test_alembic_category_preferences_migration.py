"""PG round-trip of 20260630_0001 category preferences."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_REVISION = "20260630_0001"
_PRIOR = "20260629_0002"
_TABLE = "category_preferences"
_INDEXES = {
    "ix_category_preferences_public_id",
    "ix_category_preferences_tenant_id",
    "ix_category_preferences_key",
    "ix_category_preferences_tenant_key",
    "ix_category_preferences_tenant_name",
    "ix_category_preferences_tenant_deleted",
}


def _columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns(_TABLE)}


def _index_names() -> set[str]:
    return {idx["name"] for idx in inspect(engine).get_indexes(_TABLE)}


def _unique_names() -> set[str]:
    return {item["name"] for item in inspect(engine).get_unique_constraints(_TABLE)}


def _check_names() -> set[str]:
    return {item["name"] for item in inspect(engine).get_check_constraints(_TABLE)}


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
    assert inspect(engine).has_table(_TABLE)
    cols = _columns()
    for column in (
        "public_id",
        "tenant_id",
        "name",
        "key",
        "kind",
        "created_at",
        "updated_at",
        "row_version",
        "deleted_at",
    ):
        assert column in cols
    assert cols["public_id"]["nullable"] is False
    assert cols["tenant_id"]["nullable"] is False
    assert cols["row_version"]["nullable"] is False
    assert "uq_category_preferences_tenant_key" in _unique_names()
    assert "ck_category_preferences_kind_valid" in _check_names()
    assert _INDEXES.issubset(_index_names())


def test_add_category_preferences_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()

        _run_alembic(command.stamp, _REVISION)
        _run_alembic(command.downgrade, _PRIOR)
        assert not inspect(engine).has_table(_TABLE)

        _run_alembic(command.upgrade, "head")
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
