"""PostgreSQL round-trip for the installation-owner claim receipt."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import SessionLocal, engine
from app.database_model_registry import Base
from app.services.identity_service import bootstrap_installation_owner
from tests._infra.c07_alembic import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db

_PREVIOUS_REVISION = "20260802_0001"
_TARGET_REVISION = "20260809_0001"
_TABLE = "installation_owner_claims"
_COLUMNS = {
    "operation_id",
    "installation_id",
    "request_fingerprint",
    "active_secret_hash",
    "account_id",
    "device_id",
    "ledger_id",
    "pairing_code_id",
    "pairing_derivation_index",
    "generation",
    "created_at",
    "updated_at",
}
_CHECKS = {
    "ck_installation_owner_claim_generation",
    "ck_installation_owner_claim_pairing_index",
    "ck_installation_owner_claim_request_fingerprint",
    "ck_installation_owner_claim_secret_hash",
}
_UNIQUES = {
    "uq_installation_owner_claim_active_secret_hash": ("active_secret_hash",),
    "uq_installation_owner_claim_installation_id": ("installation_id",),
    "uq_installation_owner_claim_pairing_code_id": ("pairing_code_id",),
}
_FOREIGN_KEYS = {
    "fk_installation_owner_claim_account": (
        ("account_id",), "accounts", ("id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_device": (
        ("device_id",), "devices", ("id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_ledger": (
        ("ledger_id",), "ledgers", ("ledger_id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_pairing": (
        ("pairing_code_id",), "pairing_codes", ("id",), "RESTRICT",
    ),
    "fk_installation_owner_claim_secret": (
        ("active_secret_hash",),
        "bootstrap_secret_consumptions",
        ("secret_hash",),
        "RESTRICT",
    ),
}
_INDEXES = {
    "pk_installation_owner_claims",
    *_UNIQUES,
}


def _alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    return config


def _run_alembic(action, *args: str) -> None:
    run_alembic_for_test(engine, _alembic_config(), action, *args)


def _current_revision() -> str | None:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def _assert_full_shape() -> None:
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    assert set(columns) == _COLUMNS
    assert all(columns[name]["nullable"] is False for name in _COLUMNS)
    assert inspector.get_pk_constraint(_TABLE)["constrained_columns"] == ["operation_id"]
    assert {check["name"] for check in inspector.get_check_constraints(_TABLE)} == _CHECKS
    assert {
        unique["name"]: tuple(unique["column_names"])
        for unique in inspector.get_unique_constraints(_TABLE)
    } == _UNIQUES
    assert {
        foreign_key["name"]: (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
            str(foreign_key.get("options", {}).get("ondelete", "")),
        )
        for foreign_key in inspector.get_foreign_keys(_TABLE)
    } == _FOREIGN_KEYS
    with engine.connect() as connection:
        assert {
            str(index_name)
            for (index_name,) in connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = :table"
                ),
                {"table": _TABLE},
            )
        } == _INDEXES


def test_installation_owner_claim_round_trips_on_postgres() -> None:
    reset_public_schema(engine)
    try:
        Base.metadata.create_all(bind=engine)
        _run_alembic(command.stamp, _TARGET_REVISION)
        _assert_full_shape()

        _run_alembic(command.downgrade, _PREVIOUS_REVISION)
        assert _TABLE not in inspect(engine).get_table_names()
        assert _current_revision() == _PREVIOUS_REVISION

        _run_alembic(command.upgrade, "head")
        assert _current_revision() == _TARGET_REVISION
        _assert_full_shape()
        postcondition = import_module(
            "migrations.versions.20260809_0001_add_installation_owner_claim"
        ).assert_postcondition
        with engine.connect() as connection:
            postcondition(connection)
    finally:
        reset_public_schema(engine)


def test_installation_owner_claim_downgrade_rejects_before_data_loss() -> None:
    reset_public_schema(engine)
    try:
        Base.metadata.create_all(bind=engine)
        _run_alembic(command.stamp, _TARGET_REVISION)
        with SessionLocal() as db:
            result = bootstrap_installation_owner(
                db,
                operation_id="migration-downgrade-operation",
                installation_id="migration-downgrade-installation",
                bootstrap_secret="migration-downgrade-secret-32-bytes-minimum",
            )
        assert result.operation_id == "migration-downgrade-operation"

        with pytest.raises(
            RuntimeError,
            match="destructive downgrade is refused",
        ):
            _run_alembic(command.downgrade, _PREVIOUS_REVISION)

        assert _current_revision() == _TARGET_REVISION
        assert _TABLE in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text(f'SELECT COUNT(*) FROM "{_TABLE}"')) == 1
    finally:
        reset_public_schema(engine)
