"""add budget archive fields.

Revision ID: 20260629_0002
Revises: 20260629_0001
Create Date: 2026-06-29

ADR-0052 slice 2 treats a monthly budget as a ledger-month configuration,
not as master data. Archiving the parent ``budgets`` row moves that month into
the recycle bin while preserving ``budget_categories`` children for restore.
``row_version`` provides the OCC token for archive/restore.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260629_0002"
down_revision: str | Sequence[str] | None = "20260629_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "budgets"
_INDEX = "ix_budgets_tenant_archived"


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_column(bind: sa.engine.Connection, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))


def _has_index(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(i.get("name") == name for i in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if not _has_column(bind, _TABLE, "row_version"):
        op.add_column(
            _TABLE,
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        )
    if not _has_column(bind, _TABLE, "archived_at"):
        op.add_column(_TABLE, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_index(bind, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, ["tenant_id", "archived_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if _has_index(bind, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_column(bind, _TABLE, "archived_at"):
        op.drop_column(_TABLE, "archived_at")
    if _has_column(bind, _TABLE, "row_version"):
        op.drop_column(_TABLE, "row_version")
