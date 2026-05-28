"""Migrations for csv_import_batches and csv_import_rows."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.database._core import _sqlite_column_names
from app.tenants import DEFAULT_TENANT_ID


def _migrate_csv_import_batches(connection) -> None:
    columns = _sqlite_column_names(connection, "csv_import_batches")
    if "tenant_id" not in columns:
        connection.execute(text(
            "ALTER TABLE csv_import_batches "
            f"ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"
        ))
    connection.execute(
        text("UPDATE csv_import_batches SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    additions = {
        "public_id": "VARCHAR(36)",
        "locked_until": "DATETIME",
        "apply_token": "VARCHAR(36)",
        "last_error": "TEXT",
        "applied_at": "DATETIME",
    }
    columns = _sqlite_column_names(connection, "csv_import_batches")
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE csv_import_batches ADD COLUMN {column_name} {column_type}"))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_csv_import_batches_id_tenant_id "
        "ON csv_import_batches (id, tenant_id)"
    ))
    columns = _sqlite_column_names(connection, "csv_import_batches")
    if "public_id" in columns:
        public_id_rows = connection.execute(
            text("SELECT id FROM csv_import_batches WHERE public_id IS NULL OR public_id = ''")
        ).mappings()
        for row in public_id_rows:
            connection.execute(
                text("UPDATE csv_import_batches SET public_id = :public_id WHERE id = :id"),
                {"public_id": str(uuid4()), "id": row["id"]},
            )
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_csv_import_batches_public_id "
            "ON csv_import_batches (public_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_csv_import_batches_tenant_public_id "
            "ON csv_import_batches (tenant_id, public_id)"
        ))
    if {"status", "created_at"}.issubset(columns):
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_csv_import_batches_tenant_status_created_at "
            "ON csv_import_batches (tenant_id, status, created_at)"
        ))


def _migrate_csv_import_batches_apply_token(connection) -> None:
    """Second pass on csv_import_batches: ensure apply_token column exists.

    Kept separate because the legacy migrator runs this *after* the
    csv_import_rows pass — historical ordering preserved.
    """
    columns = _sqlite_column_names(connection, "csv_import_batches")
    if "apply_token" not in columns:
        connection.execute(text("ALTER TABLE csv_import_batches ADD COLUMN apply_token VARCHAR(36)"))


def _migrate_csv_import_rows(connection, *, default_home: str, source_base: str) -> None:
    columns = _sqlite_column_names(connection, "csv_import_rows")
    if "tenant_id" not in columns:
        connection.execute(text(
            "ALTER TABLE csv_import_rows "
            f"ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"
        ))
        columns.add("tenant_id")
    connection.execute(
        text(
            "UPDATE csv_import_rows "
            "SET tenant_id = COALESCE(("
            "SELECT batch.tenant_id FROM csv_import_batches AS batch "
            "WHERE batch.id = csv_import_rows.batch_id"
            "), :tenant_id) "
            "WHERE tenant_id IS NULL OR tenant_id = ''"
        ),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    additions = {
        "apply_token": "VARCHAR(36)",
        "expense_id": "INTEGER",
        "original_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
        "original_amount_minor": "INTEGER",
        "exchange_rate_to_cny": "NUMERIC(18, 8)",
        "exchange_rate_date": "DATE",
        "exchange_rate_source": "VARCHAR(32)",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE csv_import_rows ADD COLUMN {column_name} {column_type}"))
    connection.execute(
        text(
            "UPDATE csv_import_rows SET original_currency_code = :home "
            "WHERE original_currency_code IS NULL OR original_currency_code = ''"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE csv_import_rows SET original_amount_minor = amount_cents "
            "WHERE original_amount_minor IS NULL "
            "AND amount_cents IS NOT NULL "
            "AND original_currency_code = :home"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE csv_import_rows SET exchange_rate_to_cny = 1 "
            "WHERE exchange_rate_to_cny IS NULL "
            "AND amount_cents IS NOT NULL "
            "AND original_currency_code = :home"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE csv_import_rows SET exchange_rate_source = :source_base "
            "WHERE exchange_rate_source IS NULL AND original_currency_code = :home"
        ),
        {"source_base": source_base, "home": default_home},
    )
    columns = _sqlite_column_names(connection, "csv_import_rows")
    if {"tenant_id", "batch_id", "line_number"}.issubset(columns):
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_csv_import_rows_tenant_batch_line "
            "ON csv_import_rows (tenant_id, batch_id, line_number)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_csv_import_rows_tenant_batch_line "
            "ON csv_import_rows (tenant_id, batch_id, line_number)"
        ))
    if {"tenant_id", "batch_id", "status"}.issubset(columns):
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_csv_import_rows_tenant_batch_status "
            "ON csv_import_rows (tenant_id, batch_id, status)"
        ))
    if {"tenant_id", "expense_id"}.issubset(columns):
        if {"status", "error_code", "error_message"}.issubset(columns):
            connection.execute(
                text(
                    "UPDATE csv_import_rows "
                    "SET status = 'insert_failed', "
                    "error_code = COALESCE(error_code, 'duplicate_expense_id'), "
                    "error_message = COALESCE(error_message, 'Duplicate imported expense link removed.'), "
                    "expense_id = NULL "
                    "WHERE expense_id IS NOT NULL "
                    "AND id NOT IN ("
                    "SELECT MIN(id) FROM csv_import_rows "
                    "WHERE expense_id IS NOT NULL "
                    "GROUP BY tenant_id, expense_id"
                    ")"
                )
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_csv_import_rows_tenant_expense_id "
                "ON csv_import_rows (tenant_id, expense_id) "
                "WHERE expense_id IS NOT NULL"
            )
        )
