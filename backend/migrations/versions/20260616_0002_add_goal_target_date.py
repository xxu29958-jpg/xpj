"""add goals.target_date (ADR-0049 slice 8e-6c).

Revision ID: 20260616_0002
Revises: 20260616_0001
Create Date: 2026-06-16

ADR-0049 §7.0 / 8e-6c: a pure-external ``debt_repayment`` goal can carry an optional
payoff DEADLINE (``target_date``) that drives the On track / Ahead / At risk three-state.
It is a calendar day (``Date``), nullable, with no default and no backfill — existing
goals get ``NULL`` ("no deadline"). It is orthogonal to the goals CHECK constraints (which
constrain only ``month`` / ``target_amount_cents`` / ``goal_type``) and to the two partial-
unique scope indexes (keyed on tenant / month / goal_type / period[/ category]), so this is
a clean single-step nullable ADD — no constraint swap, no index rebuild, no three-step dance.

Dual-write shape (same as the earlier 2026-06-* revisions): ``init_db()`` runs
``create_all`` from the final-shape models (the column already exists on a brand-new DB) and
then replays every revision, so the ADD is guarded by ``_has_column`` to be an idempotent
no-op on the fresh path while still mutating an existing DB stamped at 20260616_0001.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260616_0002"
down_revision: str | Sequence[str] | None = "20260616_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "goals", "target_date"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.add_column(sa.Column("target_date", sa.Date(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "goals", "target_date"):
        with op.batch_alter_table("goals") as batch_op:
            batch_op.drop_column("target_date")
