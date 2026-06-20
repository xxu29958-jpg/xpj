"""add debts.debt_kind (ADR-0049 §7.0 / 8e-6e repayment-rhythm classification).

Revision ID: 20260620_0002
Revises: 20260620_0001
Create Date: 2026-06-20

ADR-0049 §7.0 / 8e-6e: an EXTERNAL debt's repayment rhythm gates the payoff projection
(``goal_debt_repayment_kpi``) so linear velocity extrapolation only runs where it is honest
— ``revolving`` projects, ``one_off`` / ``installment`` suppress, ``unspecified`` (default)
keeps current behavior. One stored field, N behavior branches (this slice wires the projection
gate; create accepts it). Values: ``unspecified`` / ``revolving`` / ``installment`` / ``one_off``.

NOT NULL with ``server_default='unspecified'`` — a PostgreSQL fast-default backfills every
existing row to the default in one statement (no table rewrite), and the default classifies
all existing/unclassified external debt as ``unspecified`` = keeps-projecting (no behavior
regression). The ``ck_debts_kind_valid`` CHECK is added after; its ADD VALIDATEs the just-
defaulted rows (all ``unspecified``), so this is a zero-row-rejection tightening.

The ORM model (app/models/debt.py) is the single source: ``init_db``'s ``create_all`` builds
the column + CHECK on a FRESH DB, so this migration is a guarded no-op there and only advances
an EXISTING PostgreSQL DB. Predicate text is byte-identical to the CheckConstraint in
app/models/debt.py by manual convention (the round-trip test asserts the match). ``downgrade``
drops the CHECK then the column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260620_0002"
down_revision: str | Sequence[str] | None = "20260620_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEBTS = "debts"
_KIND_CHECK = "ck_debts_kind_valid"
# Byte-identical to the CheckConstraint text in app/models/debt.py.
_KIND_PREDICATE = "debt_kind IN ('unspecified', 'revolving', 'installment', 'one_off')"


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_column(bind: sa.engine.Connection, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))


def _has_check(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(c.get("name") == name for c in sa.inspect(bind).get_check_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _DEBTS):
        return
    if not _has_column(bind, _DEBTS, "debt_kind"):
        op.add_column(
            _DEBTS,
            sa.Column(
                "debt_kind",
                sa.String(length=16),
                nullable=False,
                server_default="unspecified",
            ),
        )
    if not _has_check(bind, _DEBTS, _KIND_CHECK):
        op.create_check_constraint(_KIND_CHECK, _DEBTS, _KIND_PREDICATE)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _DEBTS):
        return
    if _has_check(bind, _DEBTS, _KIND_CHECK):
        op.drop_constraint(_KIND_CHECK, _DEBTS, type_="check")
    if _has_column(bind, _DEBTS, "debt_kind"):
        op.drop_column(_DEBTS, "debt_kind")
