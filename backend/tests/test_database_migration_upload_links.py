"""upload_links legacy schema migration."""
from __future__ import annotations

import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

import app.database as database
from app.database import engine, init_db
from tests._infra.migration_helpers import indexes, reset_empty_database, table_columns

BACKEND_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_LINK_EXPIRY_MIGRATION = (
    BACKEND_ROOT / "migrations" / "versions" / "20260528_0001_upload_link_expiry.py"
)


def test_legacy_upload_links_gain_expires_at_backfill_and_index() -> None:
    reset_empty_database()
    before_migration = datetime.now(UTC).replace(tzinfo=None)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE upload_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_hash VARCHAR(64) NOT NULL,
                    account_id INTEGER NOT NULL,
                    device_id INTEGER NOT NULL,
                    ledger_id VARCHAR(64) NOT NULL,
                    default_timezone VARCHAR(64),
                    created_at DATETIME NOT NULL,
                    last_used_at DATETIME,
                    revoked_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO upload_links "
                "(token_hash, account_id, device_id, ledger_id, default_timezone, created_at) "
                "VALUES ('legacy-upload-hash', 1, 1, 'owner', 'Asia/Shanghai', '2020-05-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO upload_links "
                "(token_hash, account_id, device_id, ledger_id, default_timezone, created_at) "
                "VALUES ('legacy-upload-hash-2', 1, 1, 'owner', 'Asia/Shanghai', '2020-06-01 00:00:00')"
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        init_db()

        assert "expires_at" in table_columns("upload_links")
        assert "ix_upload_links_expires_at" in indexes("upload_links")
        with engine.begin() as connection:
            expires_rows = list(
                connection.execute(
                    text("SELECT expires_at FROM upload_links ORDER BY id")
                ).scalars()
            )
        assert all(value is not None for value in expires_rows)
        parsed = datetime.fromisoformat(str(expires_rows[0]))
        assert parsed > before_migration + timedelta(days=1)
        assert expires_rows[0] != expires_rows[1]
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


def test_upload_link_expiry_alembic_migration_uses_configured_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(UPLOAD_LINK_EXPIRY_MIGRATION))
    ttl_days = namespace["_upload_link_ttl_days"]
    spread_days = namespace["_legacy_expiry_spread_days"]

    monkeypatch.setenv("UPLOAD_LINK_TTL_DAYS", "14")
    assert ttl_days() == 14

    monkeypatch.setenv("UPLOAD_LINK_TTL_DAYS", "bad")
    assert ttl_days() == 90

    monkeypatch.setenv("UPLOAD_LINK_LEGACY_EXPIRY_SPREAD_DAYS", "45")
    assert spread_days() == 45

    monkeypatch.setenv("UPLOAD_LINK_LEGACY_EXPIRY_SPREAD_DAYS", "bad")
    assert spread_days() == 30
