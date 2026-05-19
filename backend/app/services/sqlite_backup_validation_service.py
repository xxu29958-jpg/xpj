"""Shared SQLite backup/restore validation.

The Owner Console, maintenance scripts, and restore scripts all use this
module as the single contract for a Ticketbox database file that is safe to
list as a backup or restore into the current backend.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


REQUIRED_TICKETBOX_TABLES = {
    "accounts",
    "ledgers",
    "ledger_members",
    "devices",
    "auth_tokens",
    "upload_links",
    "pairing_codes",
    "invitations",
    "ledger_audit_logs",
    "expenses",
    "expense_items",
    "expense_splits",
    "category_rules",
    "duplicate_ignores",
    "recurring_items",
    "budgets",
    "budget_categories",
    "goals",
    "dashboard_card_preferences",
    "merchant_aliases",
    "tags",
    "expense_tags",
    "csv_import_batches",
    "csv_import_rows",
    "rule_application_batches",
    "rule_application_changes",
    "exchange_rates",
    "fx_rates",
    "schema_migrations",
    "bootstrap_secret_consumptions",
    "user_ui_preferences",
}


class SqliteBackupValidationError(RuntimeError):
    """Raised when a SQLite file is not a restorable Ticketbox database."""


def validate_sqlite_backup_file(
    path: Path | str,
    *,
    expected_backend_version: str | None = None,
) -> None:
    db_path = Path(path)
    if not db_path.is_file():
        raise SqliteBackupValidationError(f"backup file does not exist: {db_path}")

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _validate_sqlite_integrity(conn)
            _validate_ticketbox_schema(conn)
            if expected_backend_version:
                _validate_backend_version(conn, expected_backend_version)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise SqliteBackupValidationError(f"SQLite validation failed: {exc}") from exc


def is_sqlite_backup_valid(
    path: Path | str,
    *,
    expected_backend_version: str | None = None,
) -> bool:
    try:
        validate_sqlite_backup_file(path, expected_backend_version=expected_backend_version)
    except SqliteBackupValidationError:
        return False
    return True


def _validate_sqlite_integrity(conn: sqlite3.Connection) -> None:
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        detail = result[0] if result else "<no result>"
        raise SqliteBackupValidationError(f"SQLite integrity_check failed: {detail}")

    try:
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.Error as exc:
        raise SqliteBackupValidationError(f"SQLite foreign_key_check could not run: {exc}") from exc
    if fk_violations:
        samples = ", ".join(
            f"{row[0]} rowid={row[1]} parent={row[2]}"
            for row in fk_violations[:3]
        )
        raise SqliteBackupValidationError(f"SQLite foreign_key_check failed: {samples}")


def _validate_ticketbox_schema(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing = sorted(REQUIRED_TICKETBOX_TABLES - tables)
    if missing:
        raise SqliteBackupValidationError(
            "missing required Ticketbox tables: " + ", ".join(missing)
        )

    migration_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(schema_migrations)")
    }
    if "backend_version" not in migration_columns:
        raise SqliteBackupValidationError("schema_migrations.backend_version is missing")


def _validate_backend_version(conn: sqlite3.Connection, expected_backend_version: str) -> None:
    versions = {
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT backend_version FROM schema_migrations "
            "WHERE backend_version IS NOT NULL AND backend_version != ''"
        )
    }
    if expected_backend_version not in versions:
        found = ", ".join(sorted(versions)) or "<none>"
        raise SqliteBackupValidationError(
            f"backup schema was not recorded by backend {expected_backend_version}; found {found}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a restorable Ticketbox SQLite backup.")
    parser.add_argument("path")
    parser.add_argument("--expected-backend-version")
    args = parser.parse_args(argv)

    try:
        validate_sqlite_backup_file(
            args.path,
            expected_backend_version=args.expected_backend_version,
        )
    except SqliteBackupValidationError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
