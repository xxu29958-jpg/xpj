"""expenses-table integrity: column checks + duplicate scope + split integrity."""

from __future__ import annotations

from sqlalchemy import text

from app.database._core import _sqlite_column_names
from app.errors import DataIntegrityError


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
