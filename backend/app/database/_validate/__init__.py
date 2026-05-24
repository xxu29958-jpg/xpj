"""Startup-time SQLite data integrity checks.

These functions never mutate the database. They run on every process start
(via :func:`validate_sqlite_data_integrity`) and fail fast when a legacy row
would silently bypass a CHECK / UNIQUE / FK constraint that newer code
assumes. The companion ``_migrations`` package repairs schema; this package
only verifies the data those repairs landed on.

Some validators are also invoked from the migration path (e.g. before
creating partial UNIQUE indexes that the data would violate). That cross-use
is intentional — the helper is the same shape either way.

Per-table validators live in private sub-modules and are re-exported at the
package level so existing callers (``_migrations``, ``_uploads``, ``_seed``)
keep their ``from app.database._validate import _validate_X`` imports.
"""

from __future__ import annotations

from sqlalchemy import inspect

from app.database._core import engine, settings
from app.database._validate._expenses import (
    _clear_invalid_duplicate_scope_data,
    _validate_expense_core_data,
    _validate_expense_split_integrity,
)
from app.database._validate._foreign_keys import _validate_sqlite_foreign_keys
from app.database._validate._identity import (
    _validate_family_role_data,
    _validate_identity_unique_scopes,
)
from app.database._validate._legacy_unique import _validate_legacy_unique_scopes
from app.database._validate._recurring_goals import (
    _validate_goal_unique_scopes,
    _validate_recurring_item_data,
)
from app.database._validate._tenant_ids import (
    ROOT_TENANT_TABLES,
    _tenant_id_pattern,
    _validate_legacy_tenant_ids,
    _validate_root_tenant_integrity,
    _validate_tenant_child_integrity,
)

__all__ = [
    "ROOT_TENANT_TABLES",
    "validate_sqlite_data_integrity",
    "_clear_invalid_duplicate_scope_data",
    "_tenant_id_pattern",
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
