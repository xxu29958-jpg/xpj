"""add tag management columns + undo snapshot tables.

Revision ID: 20260606_0001
Revises: 20260603_0002
Create Date: 2026-06-06

ADR-0043 Slice A. Brings ``tags`` up to the management surface
(``public_id`` / ``row_version`` / ``deleted_at``) and adds the two undo
snapshot tables (``tag_mutation_undo_groups`` / ``tag_mutation_undo_items``).

Dual-write shape, same as 20260603_0001/0002: ``init_db()`` runs
``Base.metadata.create_all`` (and, on SQLite, the legacy ``migrate_sqlite_schema``)
*before* ``alembic upgrade head``, so on every normal path the columns/tables
already exist and each step here is a guarded no-op. The full bodies below are
for the pure-Alembic path (a Postgres DB advanced by Alembic alone) and for an
existing Postgres DB at 20260603_0002 that needs the new columns ALTERed in.

``public_id`` rides the cross-dialect three-step (add nullable -> backfill
uuid -> NOT NULL + unique index); ``row_version`` backfills via
``server_default='1'`` like 20260603_0001.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260606_0001"
down_revision: str | Sequence[str] | None = "20260603_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def _upgrade_tags_columns(bind) -> None:
    if not _has_column(bind, "tags", "deleted_at"):
        with op.batch_alter_table("tags") as batch_op:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_tags_tenant_deleted", "tags", ["tenant_id", "deleted_at"], unique=False)
    if not _has_column(bind, "tags", "row_version"):
        with op.batch_alter_table("tags") as batch_op:
            batch_op.add_column(
                sa.Column("row_version", sa.Integer(), nullable=False, server_default="1")
            )
    if not _has_column(bind, "tags", "public_id"):
        # Three-step: add nullable, backfill a UUID per row, then tighten to
        # NOT NULL + unique index (ix_tags_public_id matches create_all's
        # column-level ``index=True, unique=True`` name).
        with op.batch_alter_table("tags") as batch_op:
            batch_op.add_column(sa.Column("public_id", sa.String(length=36), nullable=True))
        rows = bind.execute(
            sa.text("SELECT id FROM tags WHERE public_id IS NULL OR public_id = ''")
        ).mappings().all()
        for row in rows:
            bind.execute(
                sa.text("UPDATE tags SET public_id = :pid WHERE id = :id"),
                {"pid": str(uuid4()), "id": row["id"]},
            )
        with op.batch_alter_table("tags") as batch_op:
            batch_op.alter_column("public_id", existing_type=sa.String(length=36), nullable=False)
        op.create_index("ix_tags_public_id", "tags", ["public_id"], unique=True)


def _create_undo_groups() -> None:
    op.create_table(
        "tag_mutation_undo_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mutation_public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("op", sa.String(length=16), nullable=False),
        sa.Column("source_tag_public_id", sa.String(length=36), nullable=False),
        sa.Column("source_tag_name", sa.String(length=64), nullable=False),
        sa.Column("target_tag_public_id", sa.String(length=36), nullable=True),
        sa.Column("target_tag_name", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("op IN ('delete', 'merge')", name="ck_tag_mutation_undo_groups_op_valid"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["ledgers.ledger_id"], name="fk_tag_mutation_undo_groups_tenant_ledger"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_tag_mutation_undo_groups_id_tenant_id"),
    )
    with op.batch_alter_table("tag_mutation_undo_groups", schema=None) as batch_op:
        batch_op.create_index(
            "ix_tag_mutation_undo_groups_mutation_public_id", ["mutation_public_id"], unique=True
        )
        batch_op.create_index("ix_tag_mutation_undo_groups_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index(
            "ix_tag_mutation_undo_groups_tenant_created", ["tenant_id", "created_at"], unique=False
        )


def _create_undo_items() -> None:
    op.create_table(
        "tag_mutation_undo_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("expense_public_id", sa.String(length=36), nullable=False),
        sa.Column("original_tags", sa.Text(), nullable=True),
        sa.Column("original_tag_ids", sa.Text(), nullable=False),
        sa.Column("original_row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id", "tenant_id"],
            ["tag_mutation_undo_groups.id", "tag_mutation_undo_groups.tenant_id"],
            name="fk_tag_mutation_undo_items_group_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tag_mutation_undo_items", schema=None) as batch_op:
        batch_op.create_index("ix_tag_mutation_undo_items_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index("ix_tag_mutation_undo_items_group_id", ["group_id"], unique=False)
        batch_op.create_index(
            "ix_tag_mutation_undo_items_tenant_group", ["tenant_id", "group_id"], unique=False
        )


def upgrade() -> None:
    bind = op.get_bind()
    _upgrade_tags_columns(bind)
    table_names = set(sa.inspect(bind).get_table_names())
    if "tag_mutation_undo_groups" not in table_names:
        _create_undo_groups()
    if "tag_mutation_undo_items" not in table_names:
        _create_undo_items()


def downgrade() -> None:
    bind = op.get_bind()
    table_names = set(sa.inspect(bind).get_table_names())
    if "tag_mutation_undo_items" in table_names:
        op.drop_table("tag_mutation_undo_items")
    if "tag_mutation_undo_groups" in table_names:
        op.drop_table("tag_mutation_undo_groups")
    if _has_column(bind, "tags", "public_id"):
        op.drop_index("ix_tags_public_id", table_name="tags")
        with op.batch_alter_table("tags") as batch_op:
            batch_op.drop_column("public_id")
    if _has_column(bind, "tags", "row_version"):
        with op.batch_alter_table("tags") as batch_op:
            batch_op.drop_column("row_version")
    if _has_column(bind, "tags", "deleted_at"):
        op.drop_index("ix_tags_tenant_deleted", table_name="tags")
        with op.batch_alter_table("tags") as batch_op:
            batch_op.drop_column("deleted_at")
