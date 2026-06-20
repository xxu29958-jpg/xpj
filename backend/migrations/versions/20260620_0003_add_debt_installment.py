"""add debts.installment_count / installment_period_months (ADR-0049 §B 完整 installment).

Revision ID: 20260620_0003
Revises: 20260620_0002
Create Date: 2026-06-20

ADR-0049 §B: an ``installment`` external debt carries a contractual schedule —
``installment_count`` periods of ``installment_period_months`` months each. The deterministic
payoff date (建账 + count×period months) replaces the suppressed velocity projection for an
all-installment plan; paid-period progress is DERIVED from the repayment-fact count, never stored
(§B "少存状态"). Both columns are NULL for any non-installment debt.

Shape A (nullable, no default): existing rows get NULL = "no schedule" (correct — pre-installment
external debt has none), so there is no backfill and no table rewrite. The
``ck_debts_installment_valid`` CHECK (paired-and-positive: both NULL, or both > 0) is added after
the columns; every existing row is (NULL, NULL) → satisfies it, so this is a zero-row-rejection
tightening.

The ORM model (app/models/debt.py) is the single source: ``init_db``'s ``create_all`` builds the
columns + CHECK on a FRESH DB, so this migration is a guarded no-op there and only advances an
EXISTING PostgreSQL DB. The CHECK predicate text is byte-identical to the CheckConstraint in
app/models/debt.py by manual convention (the round-trip test asserts the match). ``downgrade``
drops the CHECK then the two columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260620_0003"
down_revision: str | Sequence[str] | None = "20260620_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEBTS = "debts"
_INSTALLMENT_CHECK = "ck_debts_installment_valid"
# Byte-identical to the CheckConstraint text in app/models/debt.py.
_INSTALLMENT_PREDICATE = (
    "(installment_count IS NULL AND installment_period_months IS NULL) "
    "OR (installment_count > 0 AND installment_period_months > 0)"
)


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
    if not _has_column(bind, _DEBTS, "installment_count"):
        op.add_column(_DEBTS, sa.Column("installment_count", sa.Integer(), nullable=True))
    if not _has_column(bind, _DEBTS, "installment_period_months"):
        op.add_column(_DEBTS, sa.Column("installment_period_months", sa.Integer(), nullable=True))
    if not _has_check(bind, _DEBTS, _INSTALLMENT_CHECK):
        op.create_check_constraint(_INSTALLMENT_CHECK, _DEBTS, _INSTALLMENT_PREDICATE)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _DEBTS):
        return
    if _has_check(bind, _DEBTS, _INSTALLMENT_CHECK):
        op.drop_constraint(_INSTALLMENT_CHECK, _DEBTS, type_="check")
    if _has_column(bind, _DEBTS, "installment_period_months"):
        op.drop_column(_DEBTS, "installment_period_months")
    if _has_column(bind, _DEBTS, "installment_count"):
        op.drop_column(_DEBTS, "installment_count")
