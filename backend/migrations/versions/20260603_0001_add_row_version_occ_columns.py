"""add row_version OCC column to the six CAS-gated tables.

Revision ID: 20260603_0001
Revises: 20260602_0001
Create Date: 2026-06-03

ADR-0041 phase ③ Slice A (non-breaking): add a monotonic ``row_version``
integer to every optimistic-concurrency CAS-gated table. From this slice on
the column is *maintained* (``claim_row_with_token`` bumps it on every guarded
write), but the CAS predicate still rides ``updated_at`` — Slice B flips the
predicate and the cross-surface token contract. ``server_default='1'``
backfills existing rows in a single step (no §6 three-step needed: 1 is a
sensible default for every row). The ORM declares the column, so a fresh
``Base.metadata.create_all`` already has it — guard each add with
``_has_column`` (same shape as 713c6ff2938d).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260603_0001"
down_revision: str | Sequence[str] | None = "20260602_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "expenses",
    "category_rules",
    "merchant_aliases",
    "monthly_income_plans",
    "recurring_items",
    "goals",
)


def _has_column(bind, table_name: str, column_name: str) -> bool:
    columns = sa.inspect(bind).get_columns(table_name)
    return any(c["name"] == column_name for c in columns)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in _TABLES:
        if _has_column(bind, table_name, "row_version"):
            continue
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "row_version",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(_TABLES):
        if not _has_column(bind, table_name, "row_version"):
            continue
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("row_version")
