"""SQLite migrations for AI advisor runtime tables."""

from __future__ import annotations

from sqlalchemy import text


def _migrate_budget_advisor_quota_locks(connection, table_names: set[str]) -> None:
    if "budget_advisor_audit_logs" not in table_names:
        return
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS budget_advisor_quota_locks ("
            "tenant_id VARCHAR(64) NOT NULL PRIMARY KEY, "
            "touched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "CONSTRAINT fk_budget_advisor_quota_tenant "
            "FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)"
            ")"
        )
    )
