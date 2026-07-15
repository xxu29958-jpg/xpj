"""Real PostgreSQL upgrade contract for identity transaction receipts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.database import engine

_PREVIOUS_REVISION = "20260711_0001"
_HEAD_REVISION = "20260715_0001"
_ENROLLMENT_COLUMNS = {
    "id",
    "public_id",
    "pairing_code_id",
    "invitation_id",
    "account_id",
    "device_id",
    "ledger_id",
    "secret_hash",
    "session_token_hash",
    "session_expires_at",
    "session_soft_refresh_after",
    "expires_at",
    "last_issued_at",
    "created_at",
}
_REFRESH_COLUMNS = {
    "id",
    "public_id",
    "source_token_id",
    "replacement_token_id",
    "secret_hash",
    "session_soft_refresh_after",
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


def _seed_account_ledger_device(
    connection: Connection,
    values: dict[str, object],
) -> None:
    statements = (
        "INSERT INTO accounts (id, public_id, display_name, created_at) "
        "VALUES (101, :account_public_id, 'upgrade owner', :created_at)",
        "INSERT INTO ledgers (id, ledger_id, name, owner_account_id, created_at) "
        "VALUES (111, 'upgrade-ledger', 'upgrade ledger', 101, :created_at)",
        "INSERT INTO ledger_members (id, ledger_id, account_id, role, created_at) "
        "VALUES (121, 'upgrade-ledger', 101, 'owner', :created_at)",
        "INSERT INTO devices (id, public_id, account_id, device_name, platform, created_at) "
        "VALUES (201, :device_public_id, 101, 'upgrade phone', 'android', :created_at)",
    )
    for statement in statements:
        connection.execute(text(statement), values)


def _seed_identity_credentials(
    connection: Connection,
    values: dict[str, object],
) -> None:
    connection.execute(
        text(
            "INSERT INTO auth_tokens "
            "(id, token_hash, account_id, device_id, ledger_id, scope, created_at, expires_at, revoked_at) "
            "VALUES "
            "(401, :source_hash, 101, 201, 'upgrade-ledger', 'app', :created_at, :expires_at, :created_at), "
            "(402, :replacement_hash, 101, 201, 'upgrade-ledger', 'app', :created_at, :expires_at, NULL)"
        ),
        {**values, "source_hash": "1" * 64, "replacement_hash": "2" * 64},
    )
    connection.execute(
        text(
            "INSERT INTO pairing_codes "
            "(id, code_hash, ledger_id, account_id, expires_at, used_at, created_at) "
            "VALUES "
            "(301, :code_hash, 'upgrade-ledger', 101, :expires_at, :created_at, :created_at), "
            "(302, :pending_code_hash, 'upgrade-ledger', 101, :expires_at, NULL, :created_at)"
        ),
        {
            **values,
            "code_hash": "3" * 64,
            "pending_code_hash": "6" * 64,
        },
    )
    connection.execute(
        text(
            "INSERT INTO invitations "
            "(id, public_id, ledger_id, token_hash, role, created_by_account_id, expires_at, created_at) "
            "VALUES (311, :invitation_public_id, 'upgrade-ledger', :invite_hash, 'member', 101, "
            ":expires_at, :created_at)"
        ),
        {**values, "invite_hash": "4" * 64},
    )


def _seed_rule_application_batch(
    connection: Connection,
    values: dict[str, object],
) -> None:
    connection.execute(
        text(
            "INSERT INTO rule_application_batches "
            "(id, public_id, tenant_id, status, pending_scanned, changed_count, "
            "actor_account_id, actor_device_id, created_at) "
            "VALUES (501, :batch_public_id, 'upgrade-ledger', 'applied', 0, 0, 101, 201, :created_at)"
        ),
        values,
    )


def _seed_previous_revision() -> dict[str, object]:
    created_at = datetime.now(UTC)
    values: dict[str, object] = {
        "account_public_id": str(uuid4()),
        "device_public_id": str(uuid4()),
        "batch_public_id": str(uuid4()),
        "invitation_public_id": str(uuid4()),
        "created_at": created_at,
        "expires_at": created_at + timedelta(days=90),
    }
    with engine.begin() as connection:
        _seed_account_ledger_device(connection, values)
        _seed_identity_credentials(connection, values)
        _seed_rule_application_batch(connection, values)
    return values


def _assert_identity_schema() -> None:
    inspector = inspect(engine)
    enrollment = {
        column["name"]: column
        for column in inspector.get_columns("device_enrollment_attempts")
    }
    assert set(enrollment) == _ENROLLMENT_COLUMNS
    assert enrollment["expires_at"]["nullable"] is True
    assert enrollment["session_expires_at"]["nullable"] is True
    assert enrollment["session_soft_refresh_after"]["nullable"] is True

    pairing = {
        column["name"]: column
        for column in inspector.get_columns("pairing_codes")
    }
    assert {
        "created_by_device_id",
        "recovery_device_id",
        "revoked_at",
    } <= set(pairing)
    assert pairing["created_by_device_id"]["nullable"] is True
    assert pairing["recovery_device_id"]["nullable"] is True
    assert pairing["revoked_at"]["nullable"] is True

    pairing_fks = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys("pairing_codes")
    }
    assert pairing_fks[("created_by_device_id",)]["options"]["ondelete"] == "SET NULL"
    assert pairing_fks[("recovery_device_id",)]["options"]["ondelete"] == "RESTRICT"

    refresh = {
        column["name"]: column
        for column in inspector.get_columns("session_refresh_attempts")
    }
    assert set(refresh) == _REFRESH_COLUMNS
    assert refresh["session_soft_refresh_after"]["nullable"] is True
    assert all(
        not column["nullable"]
        for name, column in refresh.items()
        if name != "session_soft_refresh_after"
    )

    actor_device_fk = next(
        foreign_key
        for foreign_key in inspector.get_foreign_keys("rule_application_batches")
        if foreign_key["constrained_columns"] == ["actor_device_id"]
    )
    assert actor_device_fk["options"]["ondelete"] == "SET NULL"


def _insert_committed_receipts(values: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE pairing_codes SET recovery_device_id = 201 WHERE id = 301"
            )
        )
        connection.execute(
            text(
                "INSERT INTO device_enrollment_attempts "
                "(public_id, pairing_code_id, account_id, device_id, ledger_id, secret_hash, "
                "session_token_hash, session_expires_at, session_soft_refresh_after, expires_at, "
                "last_issued_at, created_at) VALUES "
                "(:enrollment_id, 301, 101, 201, 'upgrade-ledger', :secret_hash, :token_hash, "
                ":expires_at, :soft_refresh_after, :expires_at, :created_at, :created_at)"
            ),
            {
                **values,
                "enrollment_id": str(uuid4()),
                "secret_hash": "5" * 64,
                "token_hash": "2" * 64,
                "soft_refresh_after": values["expires_at"] - timedelta(days=7),
            },
        )
        connection.execute(
            text(
                "INSERT INTO session_refresh_attempts "
                "(public_id, source_token_id, replacement_token_id, secret_hash, "
                "session_soft_refresh_after, expires_at, last_issued_at, created_at) VALUES "
                "(:refresh_id, 401, 402, :secret_hash, :soft_refresh_after, :expires_at, "
                ":created_at, :created_at)"
            ),
            {
                **values,
                "refresh_id": str(uuid4()),
                "secret_hash": "6" * 64,
                "soft_refresh_after": values["expires_at"] - timedelta(days=7),
            },
        )


def test_identity_receipts_upgrade_real_previous_revision_and_reject_downgrade() -> None:
    _reset_schema()
    try:
        _run_alembic(command.upgrade, _PREVIOUS_REVISION)
        values = _seed_previous_revision()

        _run_alembic(command.upgrade, "head")
        _assert_identity_schema()
        with engine.begin() as connection:
            assert connection.scalar(
                text("SELECT public_id FROM devices WHERE id = 201")
            ) == values["device_public_id"]
            identity_rows = dict(
                connection.execute(
                    text(
                        "SELECT key, value FROM app_meta "
                        "WHERE key IN ('server_id', 'data_generation')"
                    )
                ).all()
            )
        assert set(identity_rows) == {"server_id", "data_generation"}
        assert all(str(UUID(value)) == value for value in identity_rows.values())

        _insert_committed_receipts(values)
        with pytest.raises(RuntimeError, match="irreversible identity receipt"):
            _run_alembic(command.downgrade, _PREVIOUS_REVISION)

        with engine.begin() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == _HEAD_REVISION
            assert connection.scalar(
                text("SELECT count(*) FROM device_enrollment_attempts")
            ) == 1
            assert connection.scalar(
                text("SELECT count(*) FROM session_refresh_attempts")
            ) == 1
            assert connection.scalar(
                text("SELECT recovery_device_id FROM pairing_codes WHERE id = 301")
            ) == 201
            pairing_revocations = dict(
                connection.execute(
                    text(
                        "SELECT id, revoked_at FROM pairing_codes "
                        "WHERE id IN (301, 302) ORDER BY id"
                    )
                ).all()
            )
            assert pairing_revocations[301] is None
            assert pairing_revocations[302] is not None
        _assert_identity_schema()
    finally:
        _reset_schema()
