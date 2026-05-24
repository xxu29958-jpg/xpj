"""tenant_id pattern validation + ROOT_TENANT_TABLES roster + child FK scope checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text

from app.database._core import _sqlite_column_names
from app.errors import DataIntegrityError

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


@dataclass(frozen=True)
class _TenantChildCheck:
    required_tables: frozenset[str]
    sql: str
    message: str
    required_column_table: str | None = None
    required_columns: frozenset[str] = frozenset()


_TENANT_CHILD_CHECKS: tuple[_TenantChildCheck, ...] = (
    _TenantChildCheck(
        required_tables=frozenset({"expenses"}),
        required_column_table="expenses",
        required_columns=frozenset({"tenant_id", "duplicate_of_id"}),
        sql=(
            "SELECT COUNT(*) FROM expenses AS expense "
            "LEFT JOIN expenses AS target "
            "ON target.id = expense.duplicate_of_id "
            "AND target.tenant_id = expense.tenant_id "
            "WHERE expense.duplicate_of_id IS NOT NULL "
            "AND target.id IS NULL"
        ),
        message="Invalid legacy data: expenses.duplicate_of_id contains cross-ledger expense references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"expense_items", "expenses"}),
        sql=(
            "SELECT COUNT(*) FROM expense_items AS item "
            "LEFT JOIN expenses AS expense "
            "ON expense.id = item.expense_id "
            "AND expense.tenant_id = item.tenant_id "
            "WHERE expense.id IS NULL"
        ),
        message="Invalid legacy data: expense_items contains cross-ledger expense references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"csv_import_rows", "csv_import_batches"}),
        sql=(
            "SELECT COUNT(*) FROM csv_import_rows AS row "
            "LEFT JOIN csv_import_batches AS batch "
            "ON batch.id = row.batch_id "
            "AND batch.tenant_id = row.tenant_id "
            "WHERE batch.id IS NULL"
        ),
        message="Invalid legacy data: csv_import_rows contains cross-ledger batch references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"csv_import_rows", "expenses"}),
        sql=(
            "SELECT COUNT(*) FROM csv_import_rows AS row "
            "LEFT JOIN expenses AS expense "
            "ON expense.id = row.expense_id "
            "AND expense.tenant_id = row.tenant_id "
            "WHERE row.expense_id IS NOT NULL AND expense.id IS NULL"
        ),
        message="Invalid legacy data: csv_import_rows contains cross-ledger expense references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"budget_categories", "budgets"}),
        sql=(
            "SELECT COUNT(*) FROM budget_categories AS category "
            "LEFT JOIN budgets AS budget "
            "ON budget.tenant_id = category.tenant_id "
            "AND budget.month = category.month "
            "WHERE budget.id IS NULL"
        ),
        message="Invalid legacy data: budget_categories contains rows without parent budgets",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"expense_tags", "expenses", "tags"}),
        sql=(
            "SELECT COUNT(*) FROM expense_tags AS link "
            "LEFT JOIN expenses AS expense "
            "ON expense.id = link.expense_id "
            "AND expense.tenant_id = link.tenant_id "
            "WHERE expense.id IS NULL"
        ),
        message="Invalid legacy data: expense_tags contains cross-ledger expense references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"expense_tags", "expenses", "tags"}),
        sql=(
            "SELECT COUNT(*) FROM expense_tags AS link "
            "LEFT JOIN tags AS tag "
            "ON tag.id = link.tag_id "
            "AND tag.tenant_id = link.tenant_id "
            "WHERE tag.id IS NULL"
        ),
        message="Invalid legacy data: expense_tags contains cross-ledger tag references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"duplicate_ignores", "expenses"}),
        required_column_table="duplicate_ignores",
        required_columns=frozenset({"tenant_id", "expense_id", "duplicate_of_id"}),
        sql=(
            "SELECT COUNT(*) FROM duplicate_ignores AS ignored "
            "LEFT JOIN expenses AS expense "
            "ON expense.id = ignored.expense_id "
            "AND expense.tenant_id = ignored.tenant_id "
            "WHERE expense.id IS NULL"
        ),
        message="Invalid legacy data: duplicate_ignores contains cross-ledger expense references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"duplicate_ignores", "expenses"}),
        required_column_table="duplicate_ignores",
        required_columns=frozenset({"tenant_id", "expense_id", "duplicate_of_id"}),
        sql=(
            "SELECT COUNT(*) FROM duplicate_ignores AS ignored "
            "LEFT JOIN expenses AS target "
            "ON target.id = ignored.duplicate_of_id "
            "AND target.tenant_id = ignored.tenant_id "
            "WHERE target.id IS NULL"
        ),
        message="Invalid legacy data: duplicate_ignores contains cross-ledger expense references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"rule_application_changes", "rule_application_batches", "expenses"}),
        sql=(
            "SELECT COUNT(*) FROM rule_application_changes AS change "
            "LEFT JOIN rule_application_batches AS batch "
            "ON batch.id = change.batch_id "
            "AND batch.tenant_id = change.tenant_id "
            "WHERE batch.id IS NULL"
        ),
        message="Invalid legacy data: rule_application_changes contains cross-ledger batch references",
    ),
    _TenantChildCheck(
        required_tables=frozenset({"rule_application_changes", "rule_application_batches", "expenses"}),
        sql=(
            "SELECT COUNT(*) FROM rule_application_changes AS change "
            "LEFT JOIN expenses AS expense "
            "ON expense.id = change.expense_id "
            "AND expense.tenant_id = change.tenant_id "
            "WHERE expense.id IS NULL"
        ),
        message="Invalid legacy data: rule_application_changes contains cross-ledger expense references",
    ),
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


def _validate_tenant_child_integrity(connection, table_names: set[str]) -> None:
    """Reject tenant-scoped child rows whose parent belongs to another ledger."""

    for check in _TENANT_CHILD_CHECKS:
        if not _should_run_child_check(connection, table_names, check):
            continue
        invalid = int(connection.execute(text(check.sql)).scalar_one())
        if invalid:
            raise DataIntegrityError(check.message)


def _should_run_child_check(connection, table_names: set[str], check: _TenantChildCheck) -> bool:
    if not check.required_tables.issubset(table_names):
        return False
    if check.required_column_table is None:
        return True
    columns = _sqlite_column_names(connection, check.required_column_table)
    return check.required_columns.issubset(columns)
