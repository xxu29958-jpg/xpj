"""add durable budget advisor quota lock rows.

Revision ID: 20260528_0002
Revises: 20260528_0001
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_0002"
down_revision: str | Sequence[str] | None = "20260528_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "budget_advisor_audit_logs"):
        return
    if _has_table(bind, "budget_advisor_quota_locks"):
        return
    op.create_table(
        "budget_advisor_quota_locks",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "touched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["ledgers.ledger_id"],
            name="fk_budget_advisor_quota_tenant",
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "budget_advisor_quota_locks"):
        op.drop_table("budget_advisor_quota_locks")
