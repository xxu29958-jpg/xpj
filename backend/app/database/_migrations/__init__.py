"""SQLite schema migrations — ALTER/INDEX/backfill applied on every startup.

The legacy migrator (:func:`migrate_sqlite_schema`) is idempotent end-to-end:
it ALTERs missing columns, creates missing indexes, and backfills derived
fields. :func:`record_schema_migration` /
:func:`is_schema_migration_applied` add a forward-looking ledger so future
incremental migrations can short-circuit once they have been applied; the
legacy migrator itself does not gate on it yet.

Per-table helpers live in private sub-modules (``_identity_runtime``,
``_expenses``, ``_rules``, ``_budgets_tags``, ``_csv_imports``,
``_recurring_goals``, ``_duplicates_uploads``, ``_expense_items``) and are
composed back into the orchestrator below. The two phase-1 schema repairs
(``_migrate_user_ui_preferences`` and ``_migrate_identity_runtime_schema``)
live with identity_runtime rather than under :mod:`app.database._validate`
because they mutate schema.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import inspect, text

from app.database._core import engine, settings
from app.database._migrations._budgets_tags import (
    _migrate_budgets,
    _migrate_expense_tags,
    _migrate_tags,
)
from app.database._migrations._csv_imports import (
    _migrate_csv_import_batches,
    _migrate_csv_import_batches_apply_token,
    _migrate_csv_import_rows,
)
from app.database._migrations._duplicates_uploads import (
    _migrate_duplicate_ignores,
    _migrate_upload_links,
)
from app.database._migrations._expense_items import _migrate_expense_items_for_kind
from app.database._migrations._expenses import (
    _migrate_expenses_columns,
    _migrate_expenses_indexes,
    _migrate_expenses_items_sum_status,
    _migrate_expenses_split_origin_invitation_id,
)
from app.database._migrations._identity_runtime import (
    _migrate_identity_runtime_schema,
    _migrate_user_ui_preferences,
)
from app.database._migrations._recurring_goals import (
    _migrate_goals,
    _migrate_recurring_items,
)
from app.database._migrations._rules import (
    _migrate_category_rules,
    _migrate_merchant_aliases,
    _migrate_rule_application_batches,
    _migrate_rule_application_changes,
)
from app.database._validate import (
    _clear_invalid_duplicate_scope_data,
    _validate_family_role_data,
    _validate_identity_unique_scopes,
    _validate_legacy_unique_scopes,
)
from app.fx_constants import (
    DEFAULT_HOME_CURRENCY_CODE,
    FX_SOURCE_BASE,
    FX_STATUS_PENDING,
    FX_STATUS_READY,
)
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


def migrate_sqlite_schema() -> None:  # noqa: C901 - orchestrator: gates per-table helpers on table existence; further reduction would need a (table, helper) registry which loses the explicit ordering this preserves
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
            # ADR-0029: idempotent additive column for bill split link.
            expense_columns_post2 = {
                column["name"] for column in inspect(connection).get_columns("expenses")
            }
            _migrate_expenses_split_origin_invitation_id(connection, expense_columns_post2)
