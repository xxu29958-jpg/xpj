"""Legacy unique-scope checks for budgets / merchant_aliases + recurring fan-out."""

from __future__ import annotations

from sqlalchemy import text

from app.database._core import _sqlite_column_names
from app.database._validate._recurring_goals import _validate_recurring_item_data
from app.errors import DataIntegrityError


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
