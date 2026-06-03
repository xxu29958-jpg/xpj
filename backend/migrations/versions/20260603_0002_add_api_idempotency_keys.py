"""add api_idempotency_keys table.

Revision ID: 20260603_0002
Revises: 20260603_0001
Create Date: 2026-06-03

ADR-0042 Slice A: the dedicated request-idempotency table. The ORM declares
``ApiIdempotencyKey``, so a fresh ``Base.metadata.create_all`` (the
legacy-to-alembic bridge ``init_db()`` runs before ``alembic upgrade head``)
already has the table — guard ``create_table`` to keep the revision idempotent
in that case, same shape as 534606b78a65 (ocr_facts). On the pure-Alembic path
(Postgres) this creates the table + CHECK + indexes so it matches ``create_all``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260603_0002"
down_revision: str | Sequence[str] | None = "20260603_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "api_idempotency_keys" in table_names:
        return
    op.create_table(
        "api_idempotency_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'succeeded')",
            name="ck_api_idempotency_keys_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["ledgers.ledger_id"],
            name="fk_api_idempotency_keys_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("api_idempotency_keys", schema=None) as batch_op:
        batch_op.create_index(
            "ix_api_idempotency_keys_tenant_key",
            ["tenant_id", "idempotency_key"],
            unique=True,
        )
        batch_op.create_index(
            "ix_api_idempotency_keys_expires_at",
            ["expires_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("api_idempotency_keys", schema=None) as batch_op:
        batch_op.drop_index("ix_api_idempotency_keys_expires_at")
        batch_op.drop_index("ix_api_idempotency_keys_tenant_key")
    op.drop_table("api_idempotency_keys")
