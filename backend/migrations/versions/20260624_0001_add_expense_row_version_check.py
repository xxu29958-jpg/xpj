"""add expenses.row_version >= 1 CHECK (OCC token positivity invariant).

Revision ID: 20260624_0001
Revises: 20260622_0001
Create Date: 2026-06-24

``Expense.row_version`` (ADR-0041 OCC token) is server-controlled: ``server_default=1``,
monotonic ``+1`` per update, never sourced from a client — ``0`` is only the transient
``FIRST_WRITE_ROW_VERSION`` request sentinel (expense_query.py), never persisted. A stored
row is therefore always ``>= 1``; the only way to land a 0/negative is a bad migration or a
manual DB edit. This CHECK pins that invariant in the DB, mirroring the existing
``ck_expenses_*`` family (e.g. ``ck_expenses_exchange_rate_positive``).

The ORM model (app/models/expense.py) is the single source: ``init_db``'s ``create_all``
builds the CHECK on a FRESH DB, so this migration is a guarded no-op there and only advances
an EXISTING PostgreSQL DB. A defensive ``UPDATE ... WHERE row_version < 1`` runs before the
ADD so the constraint can't fail on a hypothetical corrupt row (expected zero rows). Predicate
text is byte-identical to the ``CheckConstraint`` in app/models/expense.py (the round-trip
test asserts the match). ``downgrade`` drops the CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260624_0001"
down_revision: str | Sequence[str] | None = "20260622_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXPENSES = "expenses"
_ROW_VERSION_CHECK = "ck_expenses_row_version_positive"
# Byte-identical to the CheckConstraint text in app/models/expense.py.
_ROW_VERSION_PREDICATE = "row_version >= 1"


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_check(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(c.get("name") == name for c in sa.inspect(bind).get_check_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _EXPENSES):
        return
    if not _has_check(bind, _EXPENSES, _ROW_VERSION_CHECK):
        # Defensive: a pre-existing corrupt row (should be zero) would otherwise fail the
        # constraint ADD. row_version is server-controlled and always >= 1 by construction.
        op.execute("UPDATE expenses SET row_version = 1 WHERE row_version < 1")
        op.create_check_constraint(_ROW_VERSION_CHECK, _EXPENSES, _ROW_VERSION_PREDICATE)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _EXPENSES):
        return
    if _has_check(bind, _EXPENSES, _ROW_VERSION_CHECK):
        op.drop_constraint(_ROW_VERSION_CHECK, _EXPENSES, type_="check")
