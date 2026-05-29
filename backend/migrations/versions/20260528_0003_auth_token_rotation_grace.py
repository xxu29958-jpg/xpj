"""add auth token rotation grace window.

Revision ID: 20260528_0003
Revises: 20260528_0002
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_0003"
down_revision: str | Sequence[str] | None = "20260528_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "auth_tokens"):
        return
    if "grace_until" not in _columns(bind, "auth_tokens"):
        with op.batch_alter_table("auth_tokens") as batch_op:
            batch_op.add_column(sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "auth_tokens"):
        return
    if "grace_until" in _columns(bind, "auth_tokens"):
        with op.batch_alter_table("auth_tokens") as batch_op:
            batch_op.drop_column("grace_until")
