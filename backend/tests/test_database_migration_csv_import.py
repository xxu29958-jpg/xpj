"""csv_import_batches / csv_import_rows legacy schema migration."""
from __future__ import annotations

from sqlalchemy import text

import app.database as database
from app.database import engine, init_db
from tests._infra.migration_helpers import (
    indexes,
    reset_empty_database,
    table_columns,
)


def test_legacy_csv_import_tables_without_tenant_id_migrate_before_indexes() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE csv_import_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name VARCHAR(255) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    total_rows INTEGER NOT NULL DEFAULT 1,
                    valid_rows INTEGER NOT NULL DEFAULT 1,
                    error_rows INTEGER NOT NULL DEFAULT 0,
                    applied_rows INTEGER NOT NULL DEFAULT 0,
                    inserted_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE csv_import_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id INTEGER NOT NULL,
                    line_number INTEGER NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    amount_cents INTEGER,
                    merchant VARCHAR(255),
                    category VARCHAR(64) NOT NULL,
                    note TEXT,
                    source VARCHAR(64) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO csv_import_batches
                    (file_name, status, total_rows, valid_rows, error_rows, applied_rows,
                     inserted_count, created_at, updated_at)
                VALUES
                    ('legacy.csv', 'parsed', 1, 1, 0, 0, 0,
                     '2026-05-04 08:00:00', '2026-05-04 08:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO csv_import_rows
                    (batch_id, line_number, status, amount_cents, merchant, category,
                     source, created_at, updated_at)
                VALUES
                    (1, 2, 'valid', 1200, 'Legacy Cafe', 'Other', 'CSV',
                     '2026-05-04 08:00:00', '2026-05-04 08:00:00')
                """
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        init_db()

        assert "tenant_id" in table_columns("csv_import_batches")
        assert "tenant_id" in table_columns("csv_import_rows")
        batch_columns = table_columns("csv_import_batches")
        assert {"public_id", "locked_until", "apply_token", "last_error", "applied_at"}.issubset(
            batch_columns
        )
        assert "ix_csv_import_batches_public_id" in indexes("csv_import_batches")
        assert "uq_csv_import_batches_id_tenant_id" in indexes("csv_import_batches")
        assert "uq_csv_import_rows_tenant_batch_line" in indexes("csv_import_rows")
        with engine.begin() as connection:
            batch = connection.execute(
                text("SELECT tenant_id, public_id FROM csv_import_batches WHERE id = 1")
            ).mappings().one()
            row_tenant = connection.execute(
                text("SELECT tenant_id FROM csv_import_rows WHERE id = 1")
            ).scalar_one()
        assert batch["tenant_id"] == "owner"
        assert batch["public_id"]
        assert row_tenant == "owner"
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()
