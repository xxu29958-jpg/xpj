"""Startup-time SQLite data integrity checks.

These functions never mutate the database. They run on every process start
(via :func:`validate_sqlite_data_integrity`) and fail fast when a legacy row
would silently bypass a CHECK / UNIQUE / FK constraint that newer code
assumes. The companion ``_migrations`` module repairs schema; this module
only verifies the data those repairs landed on.

Some validators are also invoked from the migration path (e.g. before
creating partial UNIQUE indexes that the data would violate). That cross-use
is intentional — the helper is the same shape either way.
"""

from __future__ import annotations

import re

from sqlalchemy import inspect, text

from app.database._core import _sqlite_column_names, engine, settings
from app.errors import DataIntegrityError

__all__ = [
    "ROOT_TENANT_TABLES",
    "validate_sqlite_data_integrity",
    "_clear_invalid_duplicate_scope_data",
    "_validate_expense_core_data",
    "_validate_expense_split_integrity",
    "_validate_family_role_data",
    "_validate_goal_unique_scopes",
    "_validate_identity_unique_scopes",
    "_validate_legacy_tenant_ids",
    "_validate_legacy_unique_scopes",
    "_validate_recurring_item_data",
    "_validate_root_tenant_integrity",
    "_validate_sqlite_foreign_keys",
    "_validate_tenant_child_integrity",
]


ROOT_TENANT_TABLES = (
    "expenses",
    "budgets",
    "goals",
    "dashboard_card_preferences",
    "csv_import_batches",
    "category_rules",
    "rule_application_batches",
    "merchant_aliases",
    "tags",
    "recurring_items",
    "exchange_rates",
)


def _tenant_id_pattern():
    # Imported lazily so this module stays a leaf of the dependency graph
    # (app.tenants pulls in config / errors but not the database package).
    from app.tenants import TENANT_ID_PATTERN

    return TENANT_ID_PATTERN


def _validate_legacy_tenant_ids(tenant_ids: set[str], *, source: str) -> None:
    pattern: re.Pattern[str] = _tenant_id_pattern()
    invalid = sorted(tenant_id for tenant_id in tenant_ids if not pattern.fullmatch(tenant_id))
    if invalid:
        sample = ", ".join(invalid[:3])
        raise DataIntegrityError(f"Invalid legacy data: {source} contains unsupported tenant_id values: {sample}")


def validate_sqlite_data_integrity() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        table_names = set(inspect(connection).get_table_names())
        _validate_sqlite_foreign_keys(connection)
        _validate_expense_core_data(connection, table_names)
        _validate_recurring_item_data(connection, table_names)
        _validate_legacy_unique_scopes(connection, table_names)
        _validate_root_tenant_integrity(connection, table_names)
        _validate_expense_split_integrity(connection, table_names)
        _validate_tenant_child_integrity(connection, table_names)


def _validate_sqlite_foreign_keys(connection) -> None:
    try:
        violations = list(connection.execute(text("PRAGMA foreign_key_check")).mappings())
    except Exception as exc:
        raise DataIntegrityError("Invalid legacy data: SQLite foreign_key_check could not run") from exc
    if not violations:
        return
    samples = ", ".join(
        f"{row['table']} rowid={row['rowid']} parent={row['parent']}"
        for row in violations[:3]
    )
    raise DataIntegrityError(f"Invalid legacy data: SQLite foreign_key_check failed: {samples}")


def _clear_invalid_duplicate_scope_data(connection, table_names: set[str]) -> None:
    """Drop derived duplicate metadata that no longer points inside its ledger."""

    if "expenses" in table_names:
        expense_columns = _sqlite_column_names(connection, "expenses")
        if {"tenant_id", "duplicate_of_id"}.issubset(expense_columns):
            assignments = ["duplicate_of_id = NULL"]
            if "duplicate_status" in expense_columns:
                assignments.append("duplicate_status = 'none'")
            if "duplicate_reason" in expense_columns:
                assignments.append("duplicate_reason = NULL")
            connection.execute(
                text(
                    "UPDATE expenses "
                    f"SET {', '.join(assignments)} "
                    "WHERE duplicate_of_id IS NOT NULL "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM expenses AS target "
                    "WHERE target.id = expenses.duplicate_of_id "
                    "AND target.tenant_id = expenses.tenant_id"
                    ")"
                )
            )

    if {"duplicate_ignores", "expenses"}.issubset(table_names):
        ignore_columns = _sqlite_column_names(connection, "duplicate_ignores")
        if {"tenant_id", "expense_id", "duplicate_of_id"}.issubset(ignore_columns):
            connection.execute(
                text(
                    "DELETE FROM duplicate_ignores "
                    "WHERE NOT EXISTS ("
                    "SELECT 1 FROM expenses AS expense "
                    "WHERE expense.id = duplicate_ignores.expense_id "
                    "AND expense.tenant_id = duplicate_ignores.tenant_id"
                    ") "
                    "OR NOT EXISTS ("
                    "SELECT 1 FROM expenses AS target "
                    "WHERE target.id = duplicate_ignores.duplicate_of_id "
                    "AND target.tenant_id = duplicate_ignores.tenant_id"
                    ")"
                )
            )


def _validate_root_tenant_integrity(connection, table_names: set[str]) -> None:
    if "ledgers" not in table_names:
        return
    for table_name in ROOT_TENANT_TABLES:
        if table_name not in table_names:
            continue
        if "tenant_id" not in _sqlite_column_names(connection, table_name):
            continue
        invalid = int(
            connection.execute(
                text(
                    f"SELECT COUNT(*) FROM {table_name} AS root "
                    "LEFT JOIN ledgers AS ledger "
                    "ON ledger.ledger_id = root.tenant_id "
                    "WHERE ledger.ledger_id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise DataIntegrityError(
                f"Invalid legacy data: {table_name}.tenant_id references a missing ledger"
            )


def _validate_expense_core_data(connection, table_names: set[str]) -> None:
    """Reject legacy expense rows that would bypass CHECK constraints."""

    if "expenses" not in table_names:
        return

    invalid_amounts = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expenses "
                "WHERE amount_cents IS NOT NULL AND amount_cents < 0"
            )
        ).scalar_one()
    )
    if invalid_amounts:
        raise DataIntegrityError("Invalid legacy data: expenses.amount_cents contains negative values")

    invalid_statuses = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expenses "
                "WHERE status IS NULL OR status NOT IN ('pending', 'confirmed', 'rejected')"
            )
        ).scalar_one()
    )
    if invalid_statuses:
        raise DataIntegrityError("Invalid legacy data: expenses.status contains unsupported values")

    columns = _sqlite_column_names(connection, "expenses")
    if "duplicate_status" in columns:
        invalid_duplicate_statuses = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expenses "
                    "WHERE duplicate_status IS NULL OR duplicate_status NOT IN ('none', 'suspected')"
                )
            ).scalar_one()
        )
        if invalid_duplicate_statuses:
            raise DataIntegrityError("Invalid legacy data: expenses.duplicate_status contains unsupported values")

    if "original_amount_minor" in columns:
        invalid_original_amounts = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expenses "
                    "WHERE original_amount_minor IS NOT NULL AND original_amount_minor < 0"
                )
            ).scalar_one()
        )
        if invalid_original_amounts:
            raise DataIntegrityError("Invalid legacy data: expenses.original_amount_minor contains negative values")

    if "exchange_rate_to_cny" in columns:
        invalid_exchange_rates = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expenses "
                    "WHERE exchange_rate_to_cny IS NOT NULL AND exchange_rate_to_cny <= 0"
                )
            ).scalar_one()
        )
        if invalid_exchange_rates:
            raise DataIntegrityError("Invalid legacy data: expenses.exchange_rate_to_cny contains non-positive values")

    if "fx_status" in columns:
        invalid_fx_statuses = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expenses "
                    "WHERE fx_status IS NULL OR fx_status NOT IN ('ready', 'pending')"
                )
            ).scalar_one()
        )
        if invalid_fx_statuses:
            raise DataIntegrityError("Invalid legacy data: expenses.fx_status contains unsupported values")


def _validate_family_role_data(connection, table_names: set[str]) -> None:
    """Reject legacy SQLite rows that would bypass role CHECK constraints.

    SQLite cannot add CHECK constraints to an existing table with ALTER TABLE.
    Older valid databases stay compatible; malformed rows fail fast on startup
    instead of producing undefined permission behavior.
    """

    if "ledger_members" in table_names:
        invalid_members = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM ledger_members "
                    "WHERE role IS NULL OR role NOT IN ('owner', 'member', 'viewer')"
                )
            ).scalar_one()
        )
        if invalid_members:
            raise DataIntegrityError("Invalid legacy data: ledger_members.role contains unsupported values")
    if "invitations" in table_names:
        invalid_invitations = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM invitations "
                    "WHERE role IS NULL OR role NOT IN ('member', 'viewer')"
                )
            ).scalar_one()
        )
        if invalid_invitations:
            raise DataIntegrityError("Invalid legacy data: invitations.role contains unsupported values")


def _validate_identity_unique_scopes(connection, table_names: set[str]) -> None:
    """Reject legacy identity rows that cannot satisfy current parent keys."""

    if "ledgers" in table_names:
        duplicate_ledger = connection.execute(
            text(
                "SELECT ledger_id, COUNT(*) AS count "
                "FROM ledgers "
                "GROUP BY ledger_id "
                "HAVING COUNT(*) > 1 "
                "LIMIT 1"
            )
        ).mappings().first()
        if duplicate_ledger is not None:
            raise DataIntegrityError(
                "Invalid legacy data: ledgers contains duplicate ledger_id rows "
                f"for ledger_id={duplicate_ledger['ledger_id']}"
            )

    if "ledger_members" in table_names:
        duplicate_member = connection.execute(
            text(
                "SELECT ledger_id, account_id, COUNT(*) AS count "
                "FROM ledger_members "
                "GROUP BY ledger_id, account_id "
                "HAVING COUNT(*) > 1 "
                "LIMIT 1"
            )
        ).mappings().first()
        if duplicate_member is not None:
            raise DataIntegrityError(
                "Invalid legacy data: ledger_members contains duplicate ledger/account rows "
                f"for ledger_id={duplicate_member['ledger_id']} account_id={duplicate_member['account_id']}"
            )


def _validate_expense_split_integrity(connection, table_names: set[str]) -> None:
    """Reject split rows whose expense/member belongs to another ledger."""

    required = {"expense_splits", "expenses", "ledger_members"}
    if not required.issubset(table_names):
        return

    invalid_expense_refs = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expense_splits AS split "
                "LEFT JOIN expenses AS expense "
                "ON expense.id = split.expense_id "
                "AND expense.tenant_id = split.tenant_id "
                "WHERE expense.id IS NULL"
            )
        ).scalar_one()
    )
    if invalid_expense_refs:
        raise DataIntegrityError(
            "Invalid legacy data: expense_splits contains cross-ledger expense references"
        )

    invalid_member_refs = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expense_splits AS split "
                "LEFT JOIN ledger_members AS member "
                "ON member.id = split.member_id "
                "AND member.ledger_id = split.tenant_id "
                "WHERE member.id IS NULL"
            )
        ).scalar_one()
    )
    if invalid_member_refs:
        raise DataIntegrityError(
            "Invalid legacy data: expense_splits contains cross-ledger member references"
        )


def _validate_tenant_child_integrity(connection, table_names: set[str]) -> None:
    """Reject tenant-scoped child rows whose parent belongs to another ledger."""

    if "expenses" in table_names:
        expense_columns = _sqlite_column_names(connection, "expenses")
        if {"tenant_id", "duplicate_of_id"}.issubset(expense_columns):
            invalid = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM expenses AS expense "
                        "LEFT JOIN expenses AS target "
                        "ON target.id = expense.duplicate_of_id "
                        "AND target.tenant_id = expense.tenant_id "
                        "WHERE expense.duplicate_of_id IS NOT NULL "
                        "AND target.id IS NULL"
                    )
                ).scalar_one()
            )
            if invalid:
                raise DataIntegrityError(
                    "Invalid legacy data: expenses.duplicate_of_id contains cross-ledger expense references"
                )

    if {"expense_items", "expenses"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expense_items AS item "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = item.expense_id "
                    "AND expense.tenant_id = item.tenant_id "
                    "WHERE expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise DataIntegrityError("Invalid legacy data: expense_items contains cross-ledger expense references")

    if {"csv_import_rows", "csv_import_batches"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM csv_import_rows AS row "
                    "LEFT JOIN csv_import_batches AS batch "
                    "ON batch.id = row.batch_id "
                    "AND batch.tenant_id = row.tenant_id "
                    "WHERE batch.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise DataIntegrityError("Invalid legacy data: csv_import_rows contains cross-ledger batch references")

    if {"csv_import_rows", "expenses"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM csv_import_rows AS row "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = row.expense_id "
                    "AND expense.tenant_id = row.tenant_id "
                    "WHERE row.expense_id IS NOT NULL AND expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise DataIntegrityError("Invalid legacy data: csv_import_rows contains cross-ledger expense references")

    if {"budget_categories", "budgets"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM budget_categories AS category "
                    "LEFT JOIN budgets AS budget "
                    "ON budget.tenant_id = category.tenant_id "
                    "AND budget.month = category.month "
                    "WHERE budget.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise DataIntegrityError("Invalid legacy data: budget_categories contains rows without parent budgets")

    if {"expense_tags", "expenses", "tags"}.issubset(table_names):
        invalid_expenses = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expense_tags AS link "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = link.expense_id "
                    "AND expense.tenant_id = link.tenant_id "
                    "WHERE expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_expenses:
            raise DataIntegrityError("Invalid legacy data: expense_tags contains cross-ledger expense references")
        invalid_tags = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expense_tags AS link "
                    "LEFT JOIN tags AS tag "
                    "ON tag.id = link.tag_id "
                    "AND tag.tenant_id = link.tenant_id "
                    "WHERE tag.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_tags:
            raise DataIntegrityError("Invalid legacy data: expense_tags contains cross-ledger tag references")

    if {"duplicate_ignores", "expenses"}.issubset(table_names):
        ignore_columns = _sqlite_column_names(connection, "duplicate_ignores")
        if {"tenant_id", "expense_id", "duplicate_of_id"}.issubset(ignore_columns):
            invalid_expenses = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM duplicate_ignores AS ignored "
                        "LEFT JOIN expenses AS expense "
                        "ON expense.id = ignored.expense_id "
                        "AND expense.tenant_id = ignored.tenant_id "
                        "WHERE expense.id IS NULL"
                    )
                ).scalar_one()
            )
            if invalid_expenses:
                raise DataIntegrityError(
                    "Invalid legacy data: duplicate_ignores contains cross-ledger expense references"
                )
            invalid_targets = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM duplicate_ignores AS ignored "
                        "LEFT JOIN expenses AS target "
                        "ON target.id = ignored.duplicate_of_id "
                        "AND target.tenant_id = ignored.tenant_id "
                        "WHERE target.id IS NULL"
                    )
                ).scalar_one()
            )
            if invalid_targets:
                raise DataIntegrityError(
                    "Invalid legacy data: duplicate_ignores contains cross-ledger expense references"
                )

    if {"rule_application_changes", "rule_application_batches", "expenses"}.issubset(table_names):
        invalid_batches = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM rule_application_changes AS change "
                    "LEFT JOIN rule_application_batches AS batch "
                    "ON batch.id = change.batch_id "
                    "AND batch.tenant_id = change.tenant_id "
                    "WHERE batch.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_batches:
            raise DataIntegrityError("Invalid legacy data: rule_application_changes contains cross-ledger batch references")
        invalid_expenses = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM rule_application_changes AS change "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = change.expense_id "
                    "AND expense.tenant_id = change.tenant_id "
                    "WHERE expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_expenses:
            raise DataIntegrityError("Invalid legacy data: rule_application_changes contains cross-ledger expense references")


def _validate_goal_unique_scopes(connection, table_names: set[str]) -> None:
    """Reject duplicate active goals before SQLite creates partial UNIQUE indexes."""

    if "goals" not in table_names:
        return

    duplicate_total = connection.execute(
        text(
            "SELECT tenant_id, month, goal_type, period, COUNT(*) AS count "
            "FROM goals "
            "WHERE status = 'active' AND category IS NULL "
            "GROUP BY tenant_id, month, goal_type, period "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).mappings().first()
    if duplicate_total is not None:
        raise DataIntegrityError(
            "Invalid legacy data: goals contains duplicate active total goals "
            f"for tenant={duplicate_total['tenant_id']} month={duplicate_total['month']}"
        )

    duplicate_category = connection.execute(
        text(
            "SELECT tenant_id, month, goal_type, period, category, COUNT(*) AS count "
            "FROM goals "
            "WHERE status = 'active' AND category IS NOT NULL "
            "GROUP BY tenant_id, month, goal_type, period, category "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).mappings().first()
    if duplicate_category is not None:
        raise DataIntegrityError(
            "Invalid legacy data: goals contains duplicate active category goals "
            f"for tenant={duplicate_category['tenant_id']} month={duplicate_category['month']} "
            f"category={duplicate_category['category']}"
        )


def _validate_recurring_item_data(connection, table_names: set[str]) -> None:
    if "recurring_items" not in table_names:
        return
    columns = _sqlite_column_names(connection, "recurring_items")
    if "frequency" in columns:
        invalid_frequency = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM recurring_items "
                    "WHERE frequency IS NULL OR frequency NOT IN ('monthly')"
                )
            ).scalar_one()
        )
        if invalid_frequency:
            raise DataIntegrityError("Invalid legacy data: recurring_items.frequency contains unsupported values")
    if "status" in columns:
        invalid_status = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM recurring_items "
                    "WHERE status IS NULL OR status NOT IN ('active', 'paused', 'archived')"
                )
            ).scalar_one()
        )
        if invalid_status:
            raise DataIntegrityError("Invalid legacy data: recurring_items.status contains unsupported values")
    if {"tenant_id", "merchant_key", "frequency"}.issubset(columns):
        duplicate_recurring = connection.execute(
            text(
                "SELECT tenant_id, merchant_key, frequency, COUNT(*) AS count "
                "FROM recurring_items "
                "GROUP BY tenant_id, merchant_key, frequency "
                "HAVING COUNT(*) > 1 "
                "LIMIT 1"
            )
        ).mappings().first()
        if duplicate_recurring is not None:
            raise DataIntegrityError(
                "Invalid legacy data: recurring_items contains duplicate tenant/merchant/frequency rows "
                f"for tenant={duplicate_recurring['tenant_id']} merchant_key={duplicate_recurring['merchant_key']}"
            )


def _validate_legacy_unique_scopes(connection, table_names: set[str]) -> None:
    if "budgets" in table_names:
        columns = _sqlite_column_names(connection, "budgets")
        if {"tenant_id", "month"}.issubset(columns):
            duplicate_budget = connection.execute(
                text(
                    "SELECT tenant_id, month, COUNT(*) AS count "
                    "FROM budgets "
                    "GROUP BY tenant_id, month "
                    "HAVING COUNT(*) > 1 "
                    "LIMIT 1"
                )
            ).mappings().first()
            if duplicate_budget is not None:
                raise DataIntegrityError(
                    "Invalid legacy data: budgets contains duplicate tenant/month rows "
                    f"for tenant={duplicate_budget['tenant_id']} month={duplicate_budget['month']}"
                )

    if "merchant_aliases" in table_names:
        columns = _sqlite_column_names(connection, "merchant_aliases")
        if {"tenant_id", "alias_key"}.issubset(columns):
            duplicate_alias = connection.execute(
                text(
                    "SELECT tenant_id, alias_key, COUNT(*) AS count "
                    "FROM merchant_aliases "
                    "GROUP BY tenant_id, alias_key "
                    "HAVING COUNT(*) > 1 "
                    "LIMIT 1"
                )
            ).mappings().first()
            if duplicate_alias is not None:
                raise DataIntegrityError(
                    "Invalid legacy data: merchant_aliases contains duplicate tenant/alias_key rows "
                    f"for tenant={duplicate_alias['tenant_id']} alias_key={duplicate_alias['alias_key']}"
                )

    _validate_recurring_item_data(connection, table_names)
