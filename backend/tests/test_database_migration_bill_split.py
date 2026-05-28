"""bill_split_invitations legacy schema migration tests."""

from __future__ import annotations

import runpy
from pathlib import Path

from sqlalchemy import text

from app.database import engine
from tests._infra.migration_helpers import reset_empty_database

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BILL_SPLIT_PENDING_INDEX_MIGRATION = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "9d8a7c6b5e4f_add_bill_split_pending_unique_index.py"
)


def test_bill_split_pending_unique_migration_deduplicates_legacy_rows() -> None:
    reset_empty_database()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE bill_split_invitations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender_expense_id INTEGER NOT NULL,
                        receiver_account_id INTEGER NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        created_at DATETIME NOT NULL,
                        cancelled_at DATETIME
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "INSERT INTO bill_split_invitations "
                    "(id, sender_expense_id, receiver_account_id, status, created_at) "
                    "VALUES "
                    "(1, 10, 20, 'invited', '2026-05-01 00:00:00'), "
                    "(2, 10, 20, 'invited', '2026-05-02 00:00:00'), "
                    "(3, 10, 21, 'invited', '2026-05-01 00:00:00')"
                )
            )

        namespace = runpy.run_path(str(BILL_SPLIT_PENDING_INDEX_MIGRATION))
        with engine.begin() as connection:
            changed = namespace["_deduplicate_pending_invitations"](connection)
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX uq_bill_split_invitations_pending_receiver "
                    "ON bill_split_invitations "
                    "(sender_expense_id, receiver_account_id) "
                    "WHERE status = 'invited'"
                )
            )
            rows = list(
                connection.execute(
                    text(
                        "SELECT id, status, cancelled_at "
                        "FROM bill_split_invitations "
                        "ORDER BY id"
                    )
                ).mappings()
            )

        assert changed == 1
        assert rows[0]["status"] == "cancelled"
        assert rows[0]["cancelled_at"] is not None
        assert rows[1]["status"] == "invited"
        assert rows[2]["status"] == "invited"
    finally:
        reset_empty_database()
