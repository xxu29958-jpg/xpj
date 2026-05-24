"""add budget advisor audit retention window.

Revision ID: 20260524_0002
Revises: 20260524_0001
Create Date: 2026-05-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260524_0002"
down_revision: str | Sequence[str] | None = "20260524_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("budget_advisor_audit_logs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "retention_days",
                sa.Integer(),
                nullable=False,
                server_default="180",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("budget_advisor_audit_logs") as batch_op:
        batch_op.drop_column("retention_days")
