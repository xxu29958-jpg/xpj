"""Phase 1 schema repairs: identity tables + user UI preferences.

These run before any expenses table check because legacy DBs may have
identity rows that current composite FKs assume.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from app.database._core import _sqlite_column_names


def _migrate_ledger_audit_logs(connection, table_names: set[str]) -> None:
    """ADR-0038 undo: add generic resource columns to the governance audit log.

    Lets ``ledger_audit_logs`` record resource-level actions (e.g.
    ``action='undo'`` on a soft-deleted merchant_alias) alongside the existing
    family/membership rows. Purely additive nullable columns.
    """
    if "ledger_audit_logs" not in table_names:
        return
    columns = _sqlite_column_names(connection, "ledger_audit_logs")
    if "resource_type" not in columns:
        connection.execute(text("ALTER TABLE ledger_audit_logs ADD COLUMN resource_type VARCHAR(64)"))
    if "resource_public_id" not in columns:
        connection.execute(text("ALTER TABLE ledger_audit_logs ADD COLUMN resource_public_id VARCHAR(64)"))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_ledger_audit_logs_resource_public_id "
        "ON ledger_audit_logs (resource_public_id)"
    ))


def _migrate_user_ui_preferences(connection, table_names: set[str]) -> None:
    if "user_ui_preferences" not in table_names:
        return
    columns = _sqlite_column_names(connection, "user_ui_preferences")
    if {"id", "account_id", "account_name", "preferences", "updated_at"}.issubset(columns):
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_ui_preferences_account_id "
                "ON user_ui_preferences (account_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_ui_preferences_account_id "
                "ON user_ui_preferences (account_id)"
            )
        )
        return

    now = datetime.now(UTC)
    connection.execute(
        text(
            "CREATE TABLE user_ui_preferences_new ("
            "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "account_id INTEGER NOT NULL, "
            "account_name VARCHAR(128) NOT NULL, "
            "preferences TEXT NOT NULL DEFAULT '{}', "
            "updated_at DATETIME NOT NULL, "
            "FOREIGN KEY(account_id) REFERENCES accounts (id)"
            ")"
        )
    )
    if {"account_name", "preferences"}.issubset(columns):
        updated_at_expr = "pref.updated_at" if "updated_at" in columns else ":now"
        connection.execute(
            text(
                "INSERT INTO user_ui_preferences_new "
                "(account_id, account_name, preferences, updated_at) "
                "SELECT account.id, pref.account_name, COALESCE(pref.preferences, '{}'), "
                f"COALESCE({updated_at_expr}, :now) "
                "FROM user_ui_preferences AS pref "
                "JOIN accounts AS account ON account.display_name = pref.account_name "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM user_ui_preferences_new AS existing "
                "WHERE existing.account_id = account.id"
                ")"
            ),
            {"now": now},
        )
    connection.execute(text("DROP TABLE user_ui_preferences"))
    connection.execute(text("ALTER TABLE user_ui_preferences_new RENAME TO user_ui_preferences"))
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_ui_preferences_account_id "
            "ON user_ui_preferences (account_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_user_ui_preferences_account_id "
            "ON user_ui_preferences (account_id)"
        )
    )


def _migrate_identity_runtime_schema(connection, table_names: set[str]) -> None:
    """Make legacy identity tables valid parents for current composite FKs."""

    if "ledgers" in table_names:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_ledgers_ledger_id "
                "ON ledgers (ledger_id)"
            )
        )

    if "ledger_members" in table_names:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_members_id_ledger_id "
                "ON ledger_members (id, ledger_id)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_member_ledger_account "
                "ON ledger_members (ledger_id, account_id)"
            )
        )

    if "auth_tokens" in table_names:
        columns = _sqlite_column_names(connection, "auth_tokens")
        if "expires_at" not in columns:
            connection.execute(text("ALTER TABLE auth_tokens ADD COLUMN expires_at DATETIME"))
        if "grace_until" not in columns:
            connection.execute(text("ALTER TABLE auth_tokens ADD COLUMN grace_until DATETIME"))
        connection.execute(
            text(
                "UPDATE auth_tokens "
                "SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP) "
                "WHERE revoked_at IS NULL "
                "AND id NOT IN ("
                "SELECT MAX(id) FROM auth_tokens "
                "WHERE revoked_at IS NULL "
                "GROUP BY account_id, device_id, ledger_id, scope"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_auth_tokens_expires_at "
                "ON auth_tokens (expires_at)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_tokens_active_principal "
                "ON auth_tokens (account_id, device_id, ledger_id, scope) "
                "WHERE revoked_at IS NULL"
            )
        )
