"""PG round-trip of 20260722_0001 (bind repayment_drafts idempotency to account).

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

_ACCOUNT_SCOPED_COLUMNS = ["tenant_id", "created_by_account_id", "draft_idempotency_key"]
_TENANT_SCOPED_COLUMNS = ["tenant_id", "draft_idempotency_key"]


def _idem_constraint_columns() -> list[str]:
    for uc in inspect(engine).get_unique_constraints("repayment_drafts"):
        if uc["name"] == "uq_repayment_drafts_idem":
            return list(uc["column_names"])
    raise AssertionError("uq_repayment_drafts_idem missing from repayment_drafts")


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
    # Drive Alembic through the test engine's connection, one command per
    # transaction (mirrors init_db's _stamp_alembic_baseline_if_needed).
    run_alembic_for_test(engine, _alembic_cfg(), action, *args)


def test_repayment_draft_account_scoped_idem_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        # create_all builds the current ORM, which declares the account-scoped
        # (tenant_id, created_by_account_id, draft_idempotency_key) constraint.
        assert _idem_constraint_columns() == _ACCOUNT_SCOPED_COLUMNS

        _reset_empty_database()
        _run_alembic(command.upgrade, "20260722_0001")
        # Downgrade past 20260722_0001 → downgrade() re-adds the tenant-wide constraint.
        _run_alembic(command.downgrade, "20260720_0001")
        assert _idem_constraint_columns() == _TENANT_SCOPED_COLUMNS

        # Upgrade back to this revision → upgrade() restores the account-scoped constraint.
        _run_alembic(command.upgrade, "20260722_0001")
        assert _idem_constraint_columns() == _ACCOUNT_SCOPED_COLUMNS
    finally:
        _reset_empty_database()
        _drop_alembic_version()
