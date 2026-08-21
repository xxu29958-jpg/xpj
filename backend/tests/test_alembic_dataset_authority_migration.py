"""PostgreSQL round-trip for the sole H2 dataset authority."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import engine
from app.database_model_registry import Base
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

_PREVIOUS = "20260809_0001"
_TARGET = "20260821_0001"
_LEGACY_DATASET_ID = "203f908a-f0d7-433e-9250-e579eac4e664"
_LEGACY_KEYS = {
    "server_id",
    "data_generation",
    "schema_version",
    "schema_min_compatible",
}


def test_dataset_authority_revision_never_adopts_or_recreates_legacy_identity() -> None:
    revision_source = (
        Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20260821_0001_add_dataset_authority.py"
    ).read_text(encoding="utf-8")

    assert 'legacy.get("server_id")' not in revision_source
    assert "uuid5(" not in revision_source
    assert '"server_id": dataset_id' not in revision_source
    assert "op.drop_table(_TABLE)" not in revision_source
    assert "dataset authority downgrade is not supported" in revision_source

    runtime_source = (Path(__file__).resolve().parents[1] / "app" / "database" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "legacy pre-H2 fallback" not in runtime_source
    assert "SELECT value FROM app_meta WHERE key = 'schema_min_compatible'" not in runtime_source
    assert "现有 schema 缺少 dataset_authority" in runtime_source


def _config() -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    return config


def _alembic(action, *args: str) -> None:
    run_alembic_for_test(engine, _config(), action, *args)


def _legacy_database() -> None:
    reset_public_schema(engine)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE dataset_authority"))
        connection.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) VALUES "
                "('server_id', :dataset, CURRENT_TIMESTAMP), "
                "('data_generation', :generation, CURRENT_TIMESTAMP), "
                "('schema_version', '1.2.0', CURRENT_TIMESTAMP), "
                "('schema_min_compatible', '1.2.0', CURRENT_TIMESTAMP)"
            ),
            {
                "dataset": _LEGACY_DATASET_ID,
                "generation": "9620f662-1ebc-4695-bb39-bcc2ecbf3cc7",
            },
        )
    _alembic(command.stamp, _PREVIOUS)


@pytest.mark.real_db
def test_dataset_authority_creates_fresh_identity_and_retires_old_writers() -> None:
    _legacy_database()
    try:
        _alembic(command.upgrade, "head")
        assert inspect(engine).has_table("dataset_authority")
        with engine.connect() as connection:
            authority = (
                connection.execute(
                    text(
                        "SELECT dataset_id, restore_epoch, schema_revision, "
                        "schema_min_compatible, semantic_revision, restored_from_backup_id "
                        "FROM dataset_authority"
                    )
                )
                .mappings()
                .one()
            )
            keys = set(
                connection.scalars(
                    text("SELECT key FROM app_meta WHERE key = ANY(:keys)"),
                    {"keys": sorted(_LEGACY_KEYS)},
                )
            )
        assert UUID(authority["dataset_id"]).version in {1, 3, 4, 5}
        assert authority["dataset_id"] != _LEGACY_DATASET_ID
        assert authority["restore_epoch"] == 0
        assert authority["schema_revision"] == _TARGET
        assert authority["schema_min_compatible"] == "1.2.0"
        assert authority["semantic_revision"] == "ticketbox-dataset-semantics-v1"
        assert authority["restored_from_backup_id"] is None
        assert keys == set()

        with pytest.raises(RuntimeError, match="dataset authority downgrade is not supported"):
            _alembic(command.downgrade, _PREVIOUS)
        assert inspect(engine).has_table("dataset_authority")
    finally:
        reset_public_schema(engine)
