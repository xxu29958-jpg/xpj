"""Real PostgreSQL upgrade contract for desktop activation receipts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import inspect, text

from app.database import engine

pytestmark = pytest.mark.real_db

_PREVIOUS_REVISION = "20260715_0001"
_HEAD_REVISION = "20260722_0001"
_ACTIVATION_COLUMNS = {
    "id",
    "public_id",
    "token_id",
    "previous_token_id",
    "account_id",
    "device_id",
    "ledger_id",
    "secret_hash",
    "activated_at",
    "expires_at",
    "last_issued_at",
    "created_at",
}


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


def _reset_schema() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def _seed_previous_revision(values: dict[str, object]) -> None:
    statements = (
        "INSERT INTO accounts (id, public_id, display_name, created_at) "
        "VALUES (101, :account_public_id, 'upgrade owner', :created_at)",
        "INSERT INTO ledgers (id, ledger_id, name, owner_account_id, created_at) "
        "VALUES (111, 'upgrade-ledger', 'upgrade ledger', 101, :created_at)",
        "INSERT INTO ledger_members (id, ledger_id, account_id, role, created_at) "
        "VALUES (121, 'upgrade-ledger', 101, 'owner', :created_at)",
        "INSERT INTO devices (id, public_id, account_id, device_name, platform, created_at) "
        "VALUES (201, :device_public_id, 101, 'upgrade desktop', 'desktop', :created_at)",
        "INSERT INTO auth_tokens "
        "(id, token_hash, account_id, device_id, ledger_id, scope, created_at, expires_at) "
        "VALUES (401, :active_hash, 101, 201, 'upgrade-ledger', 'app', :created_at, :expires_at)",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), values)


def _assert_activation_schema() -> None:
    inspector = inspect(engine)
    activation = {
        column["name"]: column
        for column in inspector.get_columns("desktop_activation_attempts")
    }
    assert set(activation) == _ACTIVATION_COLUMNS
    assert activation["activated_at"]["nullable"] is True
    assert activation["last_issued_at"]["nullable"] is True
    assert activation["previous_token_id"]["nullable"] is True
    assert all(
        not column["nullable"]
        for name, column in activation.items()
        if name not in {"activated_at", "last_issued_at", "previous_token_id"}
    )

    foreign_keys = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys("desktop_activation_attempts")
    }
    assert foreign_keys[("token_id",)]["options"]["ondelete"] == "CASCADE"
    assert foreign_keys[("previous_token_id",)]["options"]["ondelete"] == "CASCADE"

    checks = {
        constraint["name"]: constraint
        for constraint in inspector.get_check_constraints("auth_tokens")
    }
    assert "desktop_pending" in checks["ck_auth_tokens_scope_valid"]["sqltext"]


def _assert_pending_scope_writable() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO auth_tokens "
                "(id, token_hash, account_id, device_id, ledger_id, scope, created_at, expires_at) "
                "VALUES (402, :pending_hash, 101, 201, 'upgrade-ledger', 'desktop_pending', "
                ":created_at, :expires_at)"
            ),
            {
                "pending_hash": "7" * 64,
                "created_at": datetime.now(UTC),
                "expires_at": datetime.now(UTC) + timedelta(seconds=300),
            },
        )


def _assert_invalid_scope_rejected() -> None:
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
                text(
                    "INSERT INTO auth_tokens "
                    "(id, token_hash, account_id, device_id, ledger_id, scope, created_at) "
                    "VALUES (499, :bogus_hash, 101, 201, 'upgrade-ledger', 'bogus', :created_at)"
                ),
                {"bogus_hash": "9" * 64, "created_at": datetime.now(UTC)},
            )


def _insert_committed_receipt(values: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO desktop_activation_attempts "
                "(public_id, token_id, previous_token_id, account_id, device_id, ledger_id, "
                "secret_hash, activated_at, expires_at, last_issued_at, created_at) VALUES "
                "(:public_id, 402, 401, 101, 201, 'upgrade-ledger', :secret_hash, :created_at, "
                ":expires_at, :created_at, :created_at)"
            ),
            {
                **values,
                "public_id": str(uuid4()),
                "secret_hash": "8" * 64,
            },
        )


def test_desktop_activation_upgrade_real_previous_revision_and_reject_downgrade() -> None:
    _reset_schema()
    values = {
        "account_public_id": str(uuid4()),
        "device_public_id": str(uuid4()),
        "created_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + timedelta(seconds=300),
        "active_hash": "1" * 64,
    }
    try:
        _run_alembic(command.upgrade, _PREVIOUS_REVISION)
        _seed_previous_revision(values)

        _run_alembic(command.upgrade, "head")
        _assert_activation_schema()
        _assert_pending_scope_writable()
        _assert_invalid_scope_rejected()
        _insert_committed_receipt(values)

        with pytest.raises(RuntimeError, match="irreversible desktop activation receipt"):
            _run_alembic(command.downgrade, _PREVIOUS_REVISION)

        with engine.begin() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == _HEAD_REVISION
            assert connection.scalar(text("SELECT count(*) FROM desktop_activation_attempts")) == 1
        _assert_activation_schema()
    finally:
        _reset_schema()
