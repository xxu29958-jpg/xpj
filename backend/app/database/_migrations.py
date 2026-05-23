"""SQLite schema migrations — ALTER/INDEX/backfill applied on every startup.

The legacy migrator (:func:`migrate_sqlite_schema`) is idempotent end-to-end:
it ALTERs missing columns, creates missing indexes, and backfills derived
fields. :func:`record_schema_migration` /
:func:`is_schema_migration_applied` add a forward-looking ledger so future
incremental migrations can short-circuit once they have been applied; the
legacy migrator itself does not gate on it yet.

The two private migration helpers (``_migrate_user_ui_preferences`` and
``_migrate_identity_runtime_schema``) are invoked from
``migrate_sqlite_schema`` only — they live here rather than in
:mod:`app.database._validate` because they mutate schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import inspect, text

from app.database._core import _sqlite_column_names, engine, settings
from app.database._validate import (
    _clear_invalid_duplicate_scope_data,
    _validate_family_role_data,
    _validate_goal_unique_scopes,
    _validate_identity_unique_scopes,
    _validate_legacy_unique_scopes,
    _validate_recurring_item_data,
)
from app.fx_constants import (
    DEFAULT_HOME_CURRENCY_CODE,
    FX_SOURCE_BASE,
    FX_STATUS_PENDING,
    FX_STATUS_READY,
)
from app.tenants import DEFAULT_TENANT_ID
from app.version import BACKEND_VERSION

BASELINE_MIGRATION_NAME = f"baseline-v{BACKEND_VERSION}"


__all__ = [
    "BASELINE_MIGRATION_NAME",
    "is_schema_migration_applied",
    "migrate_sqlite_schema",
    "record_schema_migration",
]


def record_schema_migration(
    name: str,
    *,
    backend_version: str | None = None,
    note: str | None = None,
) -> None:
    """Record that the named migration step has been applied.

    Idempotent: re-recording the same name is a no-op. ``backend_version``
    is what backup/restore validators match against — leaving it None means
    the row will not satisfy ``--expected-backend-version`` checks.
    """

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT OR IGNORE INTO schema_migrations "
                "(name, applied_at, backend_version, note) "
                "VALUES (:name, :applied_at, :backend_version, :note)"
            ),
            {
                "name": name,
                "applied_at": datetime.now(UTC),
                "backend_version": backend_version,
                "note": note,
            },
        )


def is_schema_migration_applied(name: str) -> bool:
    """Return True if a named migration step has previously been recorded."""

    if not settings.database_url.startswith("sqlite"):
        return False
    with engine.connect() as connection:
        if "schema_migrations" not in set(inspect(connection).get_table_names()):
            return False
        row = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :name LIMIT 1"),
            {"name": name},
        ).first()
    return row is not None


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
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_auth_tokens_expires_at "
                "ON auth_tokens (expires_at)"
            )
        )


# ---------------------------------------------------------------------------
# Per-table migrators called from ``migrate_sqlite_schema``.
#
# Each helper assumes its target table exists (the dispatcher gates on
# ``table_names``). They share the begin-block ``connection`` so all per-table
# ALTERs / UPDATEs / index creates land in the same atomic transaction.
# ---------------------------------------------------------------------------


def _expenses_required_columns(default_home: str, source_base: str, status_ready: str) -> dict[str, str]:
    return {
        "tenant_id": f"VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'",
        "public_id": "VARCHAR(36)",
        "thumbnail_path": "VARCHAR(500)",
        "duplicate_status": "VARCHAR(32) NOT NULL DEFAULT 'none'",
        "duplicate_of_id": "INTEGER",
        "duplicate_reason": "VARCHAR(500)",
        "tags": "TEXT",
        "value_score": "INTEGER",
        "regret_score": "INTEGER",
        "ocr_draft_fields": "TEXT",
        "draft_idempotency_key": "VARCHAR(128)",
        "home_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
        "original_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
        "original_amount_minor": "INTEGER",
        "exchange_rate_to_cny": "NUMERIC(18, 8)",
        "exchange_rate_date": "DATE",
        "exchange_rate_source": f"VARCHAR(32) DEFAULT '{source_base}'",
        "fx_status": f"VARCHAR(32) NOT NULL DEFAULT '{status_ready}'",
        "image_deleted_at": "DATETIME",
        "thumbnail_deleted_at": "DATETIME",
    }


def _migrate_expenses_columns(
    connection,
    *,
    existing_columns: set[str],
    default_home: str,
    source_base: str,
    status_ready: str,
    status_pending: str,
) -> None:
    """Add missing columns + backfill FX-related fields on expenses."""
    required = _expenses_required_columns(default_home, source_base, status_ready)
    for name, ddl in required.items():
        if name not in existing_columns:
            connection.execute(text(f"ALTER TABLE expenses ADD COLUMN {name} {ddl}"))

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_expenses_id_tenant_id "
            "ON expenses (id, tenant_id)"
        )
    )
    connection.execute(
        text("UPDATE expenses SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(
        text("UPDATE expenses SET original_currency_code = :home WHERE original_currency_code IS NULL OR original_currency_code = ''"),
        {"home": default_home},
    )
    connection.execute(
        text("UPDATE expenses SET home_currency_code = :home WHERE home_currency_code IS NULL OR home_currency_code = ''"),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET original_amount_minor = amount_cents "
            "WHERE original_amount_minor IS NULL "
            "AND amount_cents IS NOT NULL "
            "AND original_currency_code = :home"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_to_cny = 1 "
            "WHERE exchange_rate_to_cny IS NULL "
            "AND amount_cents IS NOT NULL "
            "AND original_currency_code = :home"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET amount_cents = NULL "
            "WHERE original_currency_code != :home "
            "AND original_amount_minor IS NOT NULL "
            "AND exchange_rate_to_cny IS NULL"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_source = NULL "
            "WHERE original_currency_code != :home "
            "AND amount_cents IS NULL "
            "AND exchange_rate_to_cny IS NULL"
        ),
        {"home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_source = :source_base "
            "WHERE exchange_rate_source IS NULL AND original_currency_code = :home"
        ),
        {"source_base": source_base, "home": default_home},
    )
    connection.execute(
        text(
            "UPDATE expenses SET exchange_rate_date = date(COALESCE(expense_time, confirmed_at, created_at)) "
            "WHERE exchange_rate_date IS NULL AND amount_cents IS NOT NULL"
        )
    )
    connection.execute(
        text(
            "UPDATE expenses SET fx_status = :pending "
            "WHERE amount_cents IS NULL "
            "AND original_amount_minor IS NOT NULL "
            "AND original_currency_code != :home"
        ),
        {"home": default_home, "pending": status_pending},
    )
    connection.execute(
        text(
            "UPDATE expenses SET fx_status = :ready "
            "WHERE fx_status IS NULL OR fx_status = ''"
        ),
        {"ready": status_ready},
    )
    public_id_rows = connection.execute(
        text("SELECT id FROM expenses WHERE public_id IS NULL OR public_id = ''")
    ).mappings()
    for row in public_id_rows:
        connection.execute(
            text("UPDATE expenses SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid4()), "id": row["id"]},
        )


def _migrate_expenses_indexes(connection) -> None:
    """All non-unique + composite-unique indexes on expenses. Idempotent."""
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_expenses_public_id ON expenses (public_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_created_at ON expenses (status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_category_status ON expenses (category, status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_expense_time ON expenses (status, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_confirmed_at ON expenses (status, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_category_expense_time "
        "ON expenses (status, category, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_category_confirmed_at "
        "ON expenses (status, category, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_amount_merchant ON expenses (status, amount_cents, merchant)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_merchant_expense_time "
        "ON expenses (status, merchant, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_status_merchant_confirmed_at "
        "ON expenses (status, merchant, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_status ON expenses (duplicate_status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_of_id ON expenses (duplicate_of_id)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_image_hash ON expenses (image_hash)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_created_at ON expenses (tenant_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_category_status ON expenses (tenant_id, category, status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_expense_time ON expenses (tenant_id, status, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_confirmed_at ON expenses (tenant_id, status, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_category_expense_time "
        "ON expenses (tenant_id, status, category, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_category_confirmed_at "
        "ON expenses (tenant_id, status, category, confirmed_at)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_amount_merchant "
        "ON expenses (tenant_id, status, amount_cents, merchant)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_merchant_expense_time "
        "ON expenses (tenant_id, status, merchant, expense_time)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_merchant_confirmed_at "
        "ON expenses (tenant_id, status, merchant, confirmed_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_expenses_tenant_draft_idempotency_key "
        "ON expenses (tenant_id, draft_idempotency_key)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_image_hash ON expenses (tenant_id, image_hash)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_duplicate_status ON expenses (tenant_id, duplicate_status)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_original_currency_date "
        "ON expenses (tenant_id, original_currency_code, exchange_rate_date)",
        "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_fx_status ON expenses (tenant_id, fx_status)",
    )
    for sql in statements:
        connection.execute(text(sql))


def _migrate_category_rules(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("category_rules")}
    if "tenant_id" not in columns:
        connection.execute(
            text(f"ALTER TABLE category_rules ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'")
        )
    additions = {
        "amount_min_cents": "INTEGER",
        "amount_max_cents": "INTEGER",
        "source_contains": "VARCHAR(64)",
        "tag_contains": "VARCHAR(64)",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE category_rules ADD COLUMN {column_name} {column_type}"))
    connection.execute(
        text("UPDATE category_rules SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_category_rules_tenant_priority_id "
        "ON category_rules (tenant_id, priority, id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_category_rules_tenant_enabled_priority "
        "ON category_rules (tenant_id, enabled, priority, id)"
    ))


def _migrate_rule_application_batches(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_rule_application_batches_id_tenant_id "
        "ON rule_application_batches (id, tenant_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_batches_tenant_created_at "
        "ON rule_application_batches (tenant_id, created_at)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_batches_tenant_status "
        "ON rule_application_batches (tenant_id, status)"
    ))


def _migrate_rule_application_changes(connection) -> None:
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_changes_tenant_batch "
        "ON rule_application_changes (tenant_id, batch_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_rule_application_changes_tenant_expense "
        "ON rule_application_changes (tenant_id, expense_id)"
    ))


def _migrate_merchant_aliases(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_merchant_aliases_tenant_alias_key "
        "ON merchant_aliases (tenant_id, alias_key)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_merchant_aliases_tenant_canonical "
        "ON merchant_aliases (tenant_id, canonical_key)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_merchant_aliases_tenant_alias_key "
        "ON merchant_aliases (tenant_id, alias_key)"
    ))


def _migrate_budgets(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_tenant_month "
        "ON budgets (tenant_id, month)"
    ))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_budgets_tenant_month ON budgets (tenant_id, month)"))


def _migrate_tags(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_id_tenant_id ON tags (id, tenant_id)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_tenant_key ON tags (tenant_id, key)"
    ))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_key ON tags (tenant_id, key)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_name ON tags (tenant_id, name)"))


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


def _migrate_expense_tags(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_tags_tenant_expense_tag "
        "ON expense_tags (tenant_id, expense_id, tag_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_expense "
        "ON expense_tags (tenant_id, expense_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_tag "
        "ON expense_tags (tenant_id, tag_id)"
    ))


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


def _migrate_recurring_items(connection, table_names: set[str]) -> None:
    columns = _sqlite_column_names(connection, "recurring_items")
    additions = {
        "public_id": "VARCHAR(36)",
        "tenant_id": f"VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'",
        "frequency": "VARCHAR(32) NOT NULL DEFAULT 'monthly'",
        "status": "VARCHAR(32) NOT NULL DEFAULT 'active'",
        "occurrence_count": "INTEGER NOT NULL DEFAULT 0",
        "source": "VARCHAR(32) NOT NULL DEFAULT 'candidate'",
        "paused_at": "DATETIME",
        "archived_at": "DATETIME",
    }
    for column_name, column_type in additions.items():
        if column_name not in columns:
            connection.execute(text(f"ALTER TABLE recurring_items ADD COLUMN {column_name} {column_type}"))
    connection.execute(
        text("UPDATE recurring_items SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(text("UPDATE recurring_items SET frequency = 'monthly' WHERE frequency IS NULL OR frequency = ''"))
    connection.execute(text("UPDATE recurring_items SET status = 'active' WHERE status IS NULL OR status = ''"))
    public_id_rows = connection.execute(
        text("SELECT id FROM recurring_items WHERE public_id IS NULL OR public_id = ''")
    ).mappings()
    for row in public_id_rows:
        connection.execute(
            text("UPDATE recurring_items SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid4()), "id": row["id"]},
        )
    _validate_recurring_item_data(connection, table_names)
    columns = _sqlite_column_names(connection, "recurring_items")
    if "public_id" in columns:
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_recurring_items_public_id "
            "ON recurring_items (public_id)"
        ))
    if {"tenant_id", "merchant_key", "frequency"}.issubset(columns):
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_recurring_items_tenant_merchant_frequency "
            "ON recurring_items (tenant_id, merchant_key, frequency)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_recurring_items_tenant_merchant "
            "ON recurring_items (tenant_id, merchant_key)"
        ))
    if {"tenant_id", "status", "next_expected_date"}.issubset(columns):
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_recurring_items_tenant_status_next "
            "ON recurring_items (tenant_id, status, next_expected_date)"
        ))


def _migrate_duplicate_ignores(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("duplicate_ignores")}
    if "tenant_id" not in columns:
        connection.execute(text(
            f"ALTER TABLE duplicate_ignores ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"
        ))
    if "kind" not in columns:
        connection.execute(text("ALTER TABLE duplicate_ignores ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'manual'"))
    connection.execute(
        text("UPDATE duplicate_ignores SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_duplicate_ignore_pair_kind "
        "ON duplicate_ignores (expense_id, duplicate_of_id, kind)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_duplicate_ignore_tenant_pair_kind "
        "ON duplicate_ignores (tenant_id, expense_id, duplicate_of_id, kind)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_duplicate_ignores_tenant_pair_kind "
        "ON duplicate_ignores (tenant_id, expense_id, duplicate_of_id, kind)"
    ))


def _migrate_goals(connection, table_names: set[str]) -> None:
    _validate_goal_unique_scopes(connection, table_names)
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_active_total_scope "
        "ON goals (tenant_id, month, goal_type, period) "
        "WHERE status = 'active' AND category IS NULL"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_active_category_scope "
        "ON goals (tenant_id, month, goal_type, period, category) "
        "WHERE status = 'active' AND category IS NOT NULL"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_goals_tenant_month_status "
        "ON goals (tenant_id, month, status)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_goals_tenant_category_month "
        "ON goals (tenant_id, category, month)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_goals_tenant_public_id "
        "ON goals (tenant_id, public_id)"
    ))


def _migrate_expense_items_for_kind(connection, table_names: set[str]) -> None:
    """ADR-0035: rebuild expense_items to add kind enum + new CHECK constraints.

    The legacy ``ck_expense_items_amount_non_negative`` CHECK blocks
    ``kind='discount'`` rows (negative amount). SQLite cannot drop a CHECK
    constraint in-place, so the standard cookbook is a table rebuild:

    1. CREATE TABLE expense_items_v1 with new shape
    2. INSERT ... SELECT to copy (defaulting kind='product')
    3. DROP TABLE expense_items
    4. RENAME expense_items_v1 → expense_items
    5. Recreate indexes

    Idempotent: returns early if the new ``kind`` column is already present.
    No other tables FK-reference ``expense_items``, so PRAGMA foreign_keys
    juggling is unnecessary.
    """
    if "expense_items" not in table_names:
        return
    existing_columns = _sqlite_column_names(connection, "expense_items")
    if "kind" in existing_columns:
        return

    connection.execute(text("""
        CREATE TABLE expense_items_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id VARCHAR(36) NOT NULL UNIQUE,
            tenant_id VARCHAR(64) NOT NULL,
            expense_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            kind VARCHAR(32) NOT NULL DEFAULT 'product',
            name VARCHAR(255) NOT NULL,
            quantity_text VARCHAR(64),
            unit_price_cents INTEGER,
            amount_cents INTEGER,
            category VARCHAR(64) NOT NULL DEFAULT '其他',
            raw_text TEXT,
            confidence FLOAT,
            is_ocr_draft BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT ck_expense_items_position_non_negative CHECK (position >= 0),
            CONSTRAINT ck_expense_items_unit_price_non_negative CHECK (unit_price_cents IS NULL OR unit_price_cents >= 0),
            CONSTRAINT ck_expense_items_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            CONSTRAINT ck_expense_items_kind_valid CHECK (kind IN ('product', 'discount', 'tax', 'service_fee')),
            CONSTRAINT ck_expense_items_amount_by_kind CHECK (
                (kind = 'product' AND (amount_cents IS NULL OR amount_cents >= 0))
                OR (kind = 'discount' AND (amount_cents IS NULL OR amount_cents <= 0))
                OR (kind IN ('tax', 'service_fee') AND (amount_cents IS NULL OR amount_cents >= 0))
            ),
            CONSTRAINT fk_expense_items_expense_tenant FOREIGN KEY (expense_id, tenant_id) REFERENCES expenses(id, tenant_id),
            CONSTRAINT uq_expense_items_tenant_expense_position UNIQUE (tenant_id, expense_id, position)
        )
    """))
    connection.execute(text("""
        INSERT INTO expense_items_v1 (
            id, public_id, tenant_id, expense_id, position, kind, name, quantity_text,
            unit_price_cents, amount_cents, category, raw_text, confidence, is_ocr_draft,
            created_at, updated_at
        )
        SELECT id, public_id, tenant_id, expense_id, position, 'product', name, quantity_text,
               unit_price_cents, amount_cents, category, raw_text, confidence, is_ocr_draft,
               created_at, updated_at
        FROM expense_items
    """))
    connection.execute(text("DROP TABLE expense_items"))
    connection.execute(text("ALTER TABLE expense_items_v1 RENAME TO expense_items"))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_expense_position "
        "ON expense_items (tenant_id, expense_id, position)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_public_id "
        "ON expense_items (tenant_id, public_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_category "
        "ON expense_items (tenant_id, category)"
    ))


def _migrate_expenses_items_sum_status(connection, existing_expense_columns: set[str]) -> None:
    """ADR-0035: add expenses.items_sum_status column + backfill from items."""
    if "items_sum_status" in existing_expense_columns:
        return
    connection.execute(text(
        "ALTER TABLE expenses ADD COLUMN items_sum_status VARCHAR(32) NOT NULL DEFAULT 'no_items'"
    ))
    connection.execute(text("""
        UPDATE expenses
        SET items_sum_status = CASE
            WHEN (SELECT COUNT(*) FROM expense_items WHERE expense_items.expense_id = expenses.id) = 0
                THEN 'no_items'
            WHEN expenses.amount_cents IS NULL
                THEN 'matched'
            WHEN (
                SELECT SUM(amount_cents) FROM expense_items
                WHERE expense_items.expense_id = expenses.id
                  AND expense_items.amount_cents IS NOT NULL
            ) IS NULL
                THEN 'matched'
            WHEN expenses.amount_cents = (
                SELECT SUM(amount_cents) FROM expense_items
                WHERE expense_items.expense_id = expenses.id
                  AND expense_items.amount_cents IS NOT NULL
            )
                THEN 'matched'
            ELSE 'mismatch_known'
        END
    """))


def _migrate_upload_links(connection) -> None:
    """v0.3.1-alpha2: backfill upload_links.public_id for rows created
    before the column existed."""
    columns = {column["name"] for column in inspect(connection).get_columns("upload_links")}
    if "public_id" not in columns:
        connection.execute(text("ALTER TABLE upload_links ADD COLUMN public_id VARCHAR(36)"))
    empty_rows = connection.execute(
        text("SELECT id FROM upload_links WHERE public_id IS NULL OR public_id = ''")
    ).mappings()
    for row in empty_rows:
        connection.execute(
            text("UPDATE upload_links SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid4()), "id": row["id"]},
        )
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_upload_links_public_id "
        "ON upload_links (public_id)"
    ))


def migrate_sqlite_schema() -> None:  # noqa: C901 - migration orchestrator: 17 branches enumerate per-table fixups; splits queued for v1.0 schema refactor
    """Orchestrate idempotent SQLite schema migration on startup.

    Two transaction phases:

    1. Identity / pref schema repairs (always run).
    2. Per-table tenant_id backfill + columns + indexes (skipped when the
       expenses table doesn't exist — fresh DB).

    The per-table helpers (`_migrate_<table>`) all share phase 2's
    connection so the whole pass is atomic.
    """
    if not settings.database_url.startswith("sqlite"):
        return

    # Phase 1 — identity + ui-preferences schema repair.
    # Use the begin-block's connection for inspection. ``inspect(engine)``
    # under StaticPool (in-memory test mode) opens an independent connection
    # wrapper whose release path would roll back any concurrent transaction.
    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        _validate_family_role_data(connection, table_names)
        _validate_identity_unique_scopes(connection, table_names)
        _migrate_identity_runtime_schema(connection, table_names)
        _validate_legacy_unique_scopes(connection, table_names)
        _migrate_user_ui_preferences(connection, table_names)

    if "expenses" not in table_names:
        return

    default_home = DEFAULT_HOME_CURRENCY_CODE
    source_base = FX_SOURCE_BASE
    status_ready = FX_STATUS_READY
    status_pending = FX_STATUS_PENDING
    with engine.connect() as inspect_conn:
        existing_columns = {column["name"] for column in inspect(inspect_conn).get_columns("expenses")}

    # Phase 2 — expenses + per-table tenant migrations. Single transaction
    # so an ALTER on table A and a backfill of table B either both land or
    # neither does. The helpers below are called in the same order as the
    # original monolithic function so any historical ordering dependency
    # is preserved.
    with engine.begin() as connection:
        _migrate_expenses_columns(
            connection,
            existing_columns=existing_columns,
            default_home=default_home,
            source_base=source_base,
            status_ready=status_ready,
            status_pending=status_pending,
        )
        _migrate_expenses_indexes(connection)

        if "category_rules" in table_names:
            _migrate_category_rules(connection)
        if "rule_application_batches" in table_names:
            _migrate_rule_application_batches(connection)
        if "rule_application_changes" in table_names:
            _migrate_rule_application_changes(connection)
        if "merchant_aliases" in table_names:
            _migrate_merchant_aliases(connection)
        if "budgets" in table_names:
            _migrate_budgets(connection)
        if "tags" in table_names:
            _migrate_tags(connection)
        if "csv_import_batches" in table_names:
            _migrate_csv_import_batches(connection)
        if "expense_tags" in table_names:
            _migrate_expense_tags(connection)
        if "csv_import_rows" in table_names:
            _migrate_csv_import_rows(connection, default_home=default_home, source_base=source_base)
        if "csv_import_batches" in table_names:
            _migrate_csv_import_batches_apply_token(connection)
        if "recurring_items" in table_names:
            _migrate_recurring_items(connection, table_names)
        if "duplicate_ignores" in table_names:
            _migrate_duplicate_ignores(connection)

        _clear_invalid_duplicate_scope_data(connection, table_names)

        if "goals" in table_names:
            _migrate_goals(connection, table_names)
        if "upload_links" in table_names:
            _migrate_upload_links(connection)
        # ADR-0035 (v1.0): rebuild expense_items for kind enum + add
        # expenses.items_sum_status. Order matters: expense_items rebuild
        # first so the items_sum_status backfill subquery sees the new shape.
        _migrate_expense_items_for_kind(connection, table_names)
        if "expenses" in table_names:
            expense_columns_post = {
                column["name"] for column in inspect(connection).get_columns("expenses")
            }
            _migrate_expenses_items_sum_status(connection, expense_columns_post)
