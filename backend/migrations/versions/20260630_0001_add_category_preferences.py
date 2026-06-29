"""add category preferences.

Revision ID: 20260630_0001
Revises: 20260629_0002
Create Date: 2026-06-30

ADR-0052 slice 3 adds a ledger-level custom category option table. Historical
``expenses.category`` values remain facts; this table only controls current
category suggestions and recycle-bin restore for custom options.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260630_0001"
down_revision: str | Sequence[str] | None = "20260629_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "category_preferences"
_INDEXES = (
    "ix_category_preferences_public_id",
    "ix_category_preferences_tenant_id",
    "ix_category_preferences_key",
    "ix_category_preferences_tenant_key",
    "ix_category_preferences_tenant_name",
    "ix_category_preferences_tenant_deleted",
)


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _has_index(bind: sa.engine.Connection, table: str, name: str) -> bool:
    return any(i.get("name") == name for i in sa.inspect(bind).get_indexes(table))


def _create_index_if_missing(
    bind: sa.engine.Connection,
    name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _has_index(bind, _TABLE, name):
        op.create_index(name, _TABLE, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("public_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="custom"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["ledgers.ledger_id"],
                name="fk_category_preferences_tenant_ledger",
            ),
            sa.UniqueConstraint("public_id", name="uq_category_preferences_public_id"),
            sa.UniqueConstraint("tenant_id", "key", name="uq_category_preferences_tenant_key"),
            sa.CheckConstraint("kind IN ('custom')", name="ck_category_preferences_kind_valid"),
        )

    _create_index_if_missing(bind, "ix_category_preferences_public_id", ["public_id"], unique=True)
    _create_index_if_missing(bind, "ix_category_preferences_tenant_id", ["tenant_id"])
    _create_index_if_missing(bind, "ix_category_preferences_key", ["key"])
    _create_index_if_missing(bind, "ix_category_preferences_tenant_key", ["tenant_id", "key"])
    _create_index_if_missing(bind, "ix_category_preferences_tenant_name", ["tenant_id", "name"])
    _create_index_if_missing(
        bind,
        "ix_category_preferences_tenant_deleted",
        ["tenant_id", "deleted_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    for index_name in _INDEXES:
        if _has_index(bind, _TABLE, index_name):
            op.drop_index(index_name, table_name=_TABLE)
    op.drop_table(_TABLE)
