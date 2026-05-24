"""add retention_days to learning + ocr_facts tables.

Revision ID: 713c6ff2938d
Revises: 534606b78a65
Create Date: 2026-05-25

v1.2 follow-up debt: ADR-0037 noted that the three append-only tables
(``algorithm_decisions`` / ``ledger_learning_events`` / ``ocr_facts``)
have no retention story. This revision mirrors the
``budget_advisor_audit_logs.retention_days`` column on each one so the
cleanup service in ``learning_cleanup_service`` can prune expired rows
on a per-row schedule. Server-default 180 matches the existing audit
log default.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "713c6ff2938d"
down_revision: str | Sequence[str] | None = "534606b78a65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    columns = sa.inspect(bind).get_columns(table_name)
    return any(c["name"] == column_name for c in columns)


def upgrade() -> None:
    # ``Base.metadata.create_all`` in init_db()'s legacy-to-alembic
    # bridge path creates these tables with the new ``retention_days``
    # column already present (because the ORM model declares it). Skip
    # the add_column in that case instead of failing.
    bind = op.get_bind()
    for table_name in (
        "algorithm_decisions",
        "ledger_learning_events",
        "ocr_facts",
    ):
        if _has_column(bind, table_name, "retention_days"):
            continue
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "retention_days",
                    sa.Integer(),
                    nullable=False,
                    server_default="180",
                )
            )


def downgrade() -> None:
    for table_name in (
        "ocr_facts",
        "ledger_learning_events",
        "algorithm_decisions",
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("retention_days")
