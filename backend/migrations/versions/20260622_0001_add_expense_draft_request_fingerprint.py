"""add expenses.draft_request_fingerprint (issue #65 slice 1).

Issue #65 slice 1 — device-scoped idempotent manual create. ``draft_idempotency_key``
already holds the ``{device_id}:{client_ref}`` composite (the dedup key + slice 3's
``local:{client_ref}`` resolution handle); this column stores the sha256 fingerprint of
the request body that first claimed that key, so a replay under the same key carrying a
materially different body is rejected (``idempotency_key_reused``) instead of silently
returning the first expense.

Clean single-step nullable ADD — existing rows get ``NULL`` ("not a client_ref create").
No default, no backfill, no constraint/index touch.

Dual-write shape (same as the earlier 2026-06-* revisions): ``init_db()`` runs
``create_all`` from the final-shape models (the column already exists on a brand-new DB)
then replays every revision, so the ADD is guarded by ``_has_column`` to be an idempotent
no-op on the fresh path while still mutating an existing DB stamped at 20260620_0003.

Revision ID: 20260622_0001
Revises: 20260620_0003
Create Date: 2026-06-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260622_0001"
down_revision: str | Sequence[str] | None = "20260620_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "expenses"
_COLUMN = "draft_request_fingerprint"


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, _TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.add_column(sa.Column(_COLUMN, sa.String(length=64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, _TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COLUMN)
