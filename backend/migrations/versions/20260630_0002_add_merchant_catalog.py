"""add merchant catalog.

Revision ID: 20260630_0002
Revises: 20260630_0001
Create Date: 2026-06-30

ADR-0053 adds a ledger-level merchant directory. Historical
``expenses.merchant`` values remain immutable facts; this table only controls
current merchant-management surfaces and recycle-bin restore.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260630_0002"
down_revision: str | Sequence[str] | None = "20260630_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "merchant_catalog"
_INDEXES = (
    "ix_merchant_catalog_public_id",
    "ix_merchant_catalog_tenant_id",
    "ix_merchant_catalog_merchant_key",
    "ix_merchant_catalog_status",
    "ix_merchant_catalog_tenant_key",
    "ix_merchant_catalog_tenant_display",
    "ix_merchant_catalog_tenant_status",
    "ix_merchant_catalog_tenant_deleted",
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
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("merchant_key", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("merged_into_public_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["ledgers.ledger_id"],
                name="fk_merchant_catalog_tenant_ledger",
            ),
            sa.UniqueConstraint("public_id", name="uq_merchant_catalog_public_id"),
            sa.UniqueConstraint("tenant_id", "merchant_key", name="uq_merchant_catalog_tenant_key"),
            sa.CheckConstraint(
                "status IN ('active', 'hidden', 'merged')",
                name="ck_merchant_catalog_status_valid",
            ),
        )

    _create_index_if_missing(bind, "ix_merchant_catalog_public_id", ["public_id"], unique=True)
    _create_index_if_missing(bind, "ix_merchant_catalog_tenant_id", ["tenant_id"])
    _create_index_if_missing(bind, "ix_merchant_catalog_merchant_key", ["merchant_key"])
    _create_index_if_missing(bind, "ix_merchant_catalog_status", ["status"])
    _create_index_if_missing(bind, "ix_merchant_catalog_tenant_key", ["tenant_id", "merchant_key"])
    _create_index_if_missing(bind, "ix_merchant_catalog_tenant_display", ["tenant_id", "display_name"])
    _create_index_if_missing(bind, "ix_merchant_catalog_tenant_status", ["tenant_id", "status"])
    _create_index_if_missing(
        bind,
        "ix_merchant_catalog_tenant_deleted",
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
