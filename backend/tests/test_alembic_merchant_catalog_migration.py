"""PG round-trip of 20260630_0002 merchant catalog."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_REVISION = "20260630_0002"
_PRIOR = "20260630_0001"
_TABLE = "merchant_catalog"
_INDEXES = {
    "ix_merchant_catalog_public_id",
    "ix_merchant_catalog_tenant_id",
    "ix_merchant_catalog_merchant_key",
    "ix_merchant_catalog_status",
    "ix_merchant_catalog_tenant_key",
    "ix_merchant_catalog_tenant_display",
    "ix_merchant_catalog_tenant_status",
    "ix_merchant_catalog_tenant_deleted",
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
        "display_name",
        "merchant_key",
        "status",
        "merged_into_public_id",
        "created_at",
        "updated_at",
        "row_version",
        "deleted_at",
    ):
        assert column in cols
    assert cols["public_id"]["nullable"] is False
    assert cols["tenant_id"]["nullable"] is False
    assert cols["display_name"]["nullable"] is False
    assert cols["merchant_key"]["nullable"] is False
    assert cols["status"]["nullable"] is False
    assert cols["row_version"]["nullable"] is False
    assert "uq_merchant_catalog_tenant_key" in _unique_names()
    assert "ck_merchant_catalog_status_valid" in _check_names()
    assert _INDEXES.issubset(_index_names())


def test_add_merchant_catalog_round_trips_on_postgres() -> None:
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
