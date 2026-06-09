"""Cross-cutting ORM schema invariants.

Standalone metadata-level checks (no DB connection) that lock structural
guarantees the rest of the suite relies on. Moved here when the SQLite→PostgreSQL
data-migration tests were retired (PG-only slim-down); the invariant itself is
engine-independent and matters more than ever on PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy import DateTime

import app.models  # noqa: F401  (populate Base.metadata)
from app.database import Base


def test_no_naive_datetime_columns_exist() -> None:
    """Every ``DateTime`` instant column must be ``timezone=True``. A naive
    ``DateTime`` column would be mis-stored against a PostgreSQL ``timestamptz``
    (interpreted in the session timezone — the month-boundary offset bug this
    project has hit twice). Lock the invariant: no naive instants."""
    naive = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, DateTime) and not getattr(column.type, "timezone", False)
    ]
    assert not naive, f"these DateTime columns must be timezone=True: {naive}"
