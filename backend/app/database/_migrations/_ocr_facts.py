"""Migration: add the composite (expense_id, tenant_id) FK to ocr_facts.

``ocr_facts`` shipped (v1.2) with a single-column ``expense_id`` FK, which let a
fact pin to an expense in a *different* ledger. ``expenses`` carries
``UNIQUE(id, tenant_id)`` precisely so children can enforce tenant scope at the
DB layer, so the fix is a composite FK to ``expenses(id, tenant_id)`` — the same
pattern ``expense_items`` already uses.

SQLite cannot add a constraint in place, so this rebuilds the table. The new
shape is created straight from the ORM metadata (never hand-written DDL) so it
can never drift from ``create_all``; only rows whose ``(expense_id, tenant_id)``
matches a real expense are copied across, dropping any orphan the old single
column FK had allowed.

Idempotent: returns early once the composite FK is present (fresh DBs get it
from ``create_all``).
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.database._core import _sqlite_column_names

logger = logging.getLogger(__name__)


def _ocr_facts_has_composite_expense_fk(connection) -> bool:
    """True when ocr_facts already has a 2-column FK into ``expenses``."""
    rows = list(
        connection.execute(text("PRAGMA foreign_key_list(ocr_facts)")).mappings()
    )
    spans: dict[int, int] = {}
    for row in rows:
        if row["table"] == "expenses":
            spans[row["id"]] = spans.get(row["id"], 0) + 1
    return any(count >= 2 for count in spans.values())


def _migrate_ocr_facts(connection, table_names: set[str]) -> None:
    if "ocr_facts" not in table_names:
        return
    if _ocr_facts_has_composite_expense_fk(connection):
        return

    # Local import keeps app.database._migrations free of an import-time
    # dependency on the model layer (which imports Base from app.database).
    from app.models.ocr_facts import OcrFact

    new_columns = [column.name for column in OcrFact.__table__.columns]

    connection.execute(text("ALTER TABLE ocr_facts RENAME TO ocr_facts_legacy"))
    # The named indexes followed the table on rename; drop them so recreating
    # the model's identically-named indexes below doesn't collide.
    legacy_indexes = list(
        connection.execute(text("PRAGMA index_list(ocr_facts_legacy)")).mappings()
    )
    for index in legacy_indexes:
        if index["origin"] == "c":  # explicit CREATE INDEX → droppable + name clashes
            connection.execute(text(f'DROP INDEX IF EXISTS "{index["name"]}"'))

    OcrFact.__table__.create(bind=connection)

    legacy_columns = _sqlite_column_names(connection, "ocr_facts_legacy")
    shared = [name for name in new_columns if name in legacy_columns]
    col_csv = ", ".join(f'"{name}"' for name in shared)
    result = connection.execute(
        text(
            f"INSERT INTO ocr_facts ({col_csv}) "
            f"SELECT {col_csv} FROM ocr_facts_legacy "
            "WHERE EXISTS ("
            "  SELECT 1 FROM expenses "
            "  WHERE expenses.id = ocr_facts_legacy.expense_id "
            "    AND expenses.tenant_id = ocr_facts_legacy.tenant_id"
            ")"
        )
    )
    copied = int(result.rowcount or 0)
    legacy_total = int(
        connection.execute(text("SELECT COUNT(*) FROM ocr_facts_legacy")).scalar() or 0
    )
    dropped = legacy_total - copied
    if dropped > 0:
        # These rows pointed at an expense in another ledger — exactly the
        # corruption the new FK forbids. The app-layer guard means this should
        # be zero in practice; log loudly if it isn't.
        logger.warning(
            "ocr_facts composite-FK migration dropped %s cross-tenant orphan row(s)",
            dropped,
        )
    connection.execute(text("DROP TABLE ocr_facts_legacy"))


__all__ = ["_migrate_ocr_facts"]
