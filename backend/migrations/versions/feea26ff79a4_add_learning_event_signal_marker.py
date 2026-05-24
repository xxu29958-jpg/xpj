"""add signal_type / signal_hash / signal_payload to ledger_learning_events.

Revision ID: feea26ff79a4
Revises: 713c6ff2938d
Create Date: 2026-05-25

v1.2 ops: replace the JSON LIKE scan inside ``_count_recent_rejects``
/ ``_has_recent_reject`` with an indexed equality lookup. JSON columns
(``before_payload`` / ``after_payload``) remain for audit; the new
columns carry the canonical marker (registry-defined subset of keys)
and its SHA-256 hash. The composite index on (tenant_id, event_type,
signal_type, signal_hash, created_at) makes "has the user recently
rejected this exact advice?" O(log n) instead of full-table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "feea26ff79a4"
down_revision: str | Sequence[str] | None = "713c6ff2938d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    columns = sa.inspect(bind).get_columns(table_name)
    return any(c["name"] == column_name for c in columns)


def _has_index(bind, table_name: str, index_name: str) -> bool:
    indexes = sa.inspect(bind).get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    bind = op.get_bind()
    # Add the three nullable marker columns. Existing rows stay NULL
    # and are excluded from the new index naturally — they only
    # influence the LIKE-fallback path that we keep around for one
    # release as a safety net.
    if not _has_column(bind, "ledger_learning_events", "signal_type"):
        with op.batch_alter_table("ledger_learning_events") as batch_op:
            batch_op.add_column(
                sa.Column("signal_type", sa.String(length=64), nullable=True)
            )
    if not _has_column(bind, "ledger_learning_events", "signal_hash"):
        with op.batch_alter_table("ledger_learning_events") as batch_op:
            batch_op.add_column(
                sa.Column("signal_hash", sa.String(length=64), nullable=True)
            )
    if not _has_column(bind, "ledger_learning_events", "signal_payload"):
        with op.batch_alter_table("ledger_learning_events") as batch_op:
            batch_op.add_column(
                sa.Column("signal_payload", sa.Text(), nullable=True)
            )
    if not _has_index(
        bind,
        "ledger_learning_events",
        "ix_ledger_learning_events_signal_lookup",
    ):
        op.create_index(
            "ix_ledger_learning_events_signal_lookup",
            "ledger_learning_events",
            ["tenant_id", "event_type", "signal_type", "signal_hash", "created_at"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_ledger_learning_events_signal_lookup",
        table_name="ledger_learning_events",
    )
    with op.batch_alter_table("ledger_learning_events") as batch_op:
        batch_op.drop_column("signal_payload")
        batch_op.drop_column("signal_hash")
        batch_op.drop_column("signal_type")
