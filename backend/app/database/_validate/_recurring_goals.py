"""recurring_items + goals uniqueness/scope integrity."""

from __future__ import annotations

from sqlalchemy import text

from app.database._core import _sqlite_column_names
from app.errors import DataIntegrityError


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
