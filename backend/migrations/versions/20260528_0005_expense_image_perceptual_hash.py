"""Add expense perceptual image hash."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260528_0005"
down_revision = "20260528_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("expenses")}
    if "image_perceptual_hash" not in columns:
        with op.batch_alter_table("expenses") as batch_op:
            batch_op.add_column(
                sa.Column("image_perceptual_hash", sa.String(length=16), nullable=True)
            )
    indexes = {index["name"] for index in inspector.get_indexes("expenses")}
    if "ix_expenses_tenant_image_phash" not in indexes:
        op.create_index(
            "ix_expenses_tenant_image_phash",
            "expenses",
            ["tenant_id", "image_perceptual_hash"],
            unique=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    indexes = {index["name"] for index in inspector.get_indexes("expenses")}
    if "ix_expenses_tenant_image_phash" in indexes:
        op.drop_index("ix_expenses_tenant_image_phash", table_name="expenses")
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_column("image_perceptual_hash")
