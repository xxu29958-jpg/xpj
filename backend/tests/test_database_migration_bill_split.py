"""bill_split_invitations legacy schema migration tests."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import engine
from tests._infra.migration_helpers import reset_empty_database

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BILL_SPLIT_PENDING_INDEX_MIGRATION = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "9d8a7c6b5e4f_add_bill_split_pending_unique_index.py"
)
SPLIT_ORIGIN_UNIQUE_MIGRATION = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "20260602_0001_bill_split_received_expense_unique.py"
)


def _create_minimal_expenses_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id VARCHAR(64),
                amount_cents INTEGER,
                status VARCHAR(32),
                split_origin_invitation_id VARCHAR(36)
            )
            """
        )
    )


def _insert_received_expense(
    connection, *, tenant_id: str, amount_cents: int, split_origin: str | None
) -> None:
    connection.execute(
        text(
            "INSERT INTO expenses "
            "(tenant_id, amount_cents, status, split_origin_invitation_id) "
            "VALUES (:tenant_id, :amount_cents, 'confirmed', :split_origin)"
        ),
        {
            "tenant_id": tenant_id,
            "amount_cents": amount_cents,
            "split_origin": split_origin,
        },
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


def test_split_origin_unique_migration_fails_loud_on_legacy_duplicates() -> None:
    """ADR-0038 PR-C: if a pre-fix concurrent accept left two received
    expenses for one invitation, the migration must NOT auto-delete money —
    it fails loud and names the affected invitation public_ids. NULLs (normal
    expenses) are never flagged."""
    reset_empty_database()
    try:
        with engine.begin() as connection:
            _create_minimal_expenses_table(connection)
            _insert_received_expense(connection, tenant_id="r", amount_cents=2500, split_origin="inv-dup")
            _insert_received_expense(connection, tenant_id="r", amount_cents=2500, split_origin="inv-dup")
            _insert_received_expense(connection, tenant_id="r", amount_cents=1000, split_origin="inv-solo")
            _insert_received_expense(connection, tenant_id="r", amount_cents=900, split_origin=None)
            _insert_received_expense(connection, tenant_id="r", amount_cents=900, split_origin=None)

        namespace = runpy.run_path(str(SPLIT_ORIGIN_UNIQUE_MIGRATION))
        with engine.begin() as connection:
            duplicates = namespace["_duplicate_split_origins"](connection)
        assert duplicates == ["inv-dup"]

        with engine.begin() as connection, pytest.raises(RuntimeError) as exc_info:
            namespace["_apply"](connection)
        assert "inv-dup" in str(exc_info.value)
        # No index was created on the failed path.
        with engine.begin() as connection:
            index_names = {
                row[1] for row in connection.execute(text("PRAGMA index_list('expenses')"))
            }
        assert "uq_expenses_split_origin_invitation" not in index_names
    finally:
        reset_empty_database()


def test_split_origin_unique_migration_clean_creates_index_and_enforces_uniqueness() -> None:
    """Clean DB: the migration creates the partial-unique index, then a second
    received expense for the same invitation is rejected while multiple NULL
    (non-split) expenses remain allowed."""
    reset_empty_database()
    try:
        with engine.begin() as connection:
            _create_minimal_expenses_table(connection)
            _insert_received_expense(connection, tenant_id="r", amount_cents=2500, split_origin="inv-1")
            _insert_received_expense(connection, tenant_id="r", amount_cents=900, split_origin=None)
            _insert_received_expense(connection, tenant_id="r", amount_cents=900, split_origin=None)

        namespace = runpy.run_path(str(SPLIT_ORIGIN_UNIQUE_MIGRATION))
        with engine.begin() as connection:
            namespace["_apply"](connection)
            index_names = {
                row[1] for row in connection.execute(text("PRAGMA index_list('expenses')"))
            }
        assert "uq_expenses_split_origin_invitation" in index_names

        # NULLs stay allowed (distinct in a UNIQUE index)…
        with engine.begin() as connection:
            _insert_received_expense(connection, tenant_id="r", amount_cents=900, split_origin=None)
        # …but a duplicate non-NULL invitation marker is now rejected.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_received_expense(
                connection, tenant_id="r", amount_cents=2500, split_origin="inv-1"
            )
    finally:
        reset_empty_database()
