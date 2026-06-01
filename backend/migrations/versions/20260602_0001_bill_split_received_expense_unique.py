"""bill split received-expense uniqueness (ADR-0038 PR-C).

Revision ID: 20260602_0001
Revises: 20260528_0005
Create Date: 2026-06-02

A concurrent double-accept of one bill-split invitation could create two
``confirmed`` received expenses — doubling the receiver's money — before
``accept_invitation`` learned to claim the invitation atomically. This
partial-UNIQUE index on ``expenses.split_origin_invitation_id`` is the
DB-level backstop: at most one received expense per invitation. Partial
because the many NULL rows (normal expenses) must not collide.

Money safety: if legacy duplicates already exist (the race fired before this
fix), the migration FAILS LOUD and lists the affected invitation public_ids
rather than auto-deleting a confirmed expense. The operator decides which
expense to keep, rejects/deletes the orphan, then re-runs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260602_0001"
down_revision: str | Sequence[str] | None = "20260528_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_expenses_split_origin_invitation"


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(bind).get_indexes(table_name)
    )


def _duplicate_split_origins(bind) -> list[str]:
    """Invitation public_ids that already have >1 received expense.

    Returned so :func:`_apply` can fail loud with an actionable list — a
    ``confirmed`` expense is money, so the migration never auto-resolves it.
    """
    rows = bind.execute(
        sa.text(
            "SELECT split_origin_invitation_id "
            "FROM expenses "
            "WHERE split_origin_invitation_id IS NOT NULL "
            "GROUP BY split_origin_invitation_id "
            "HAVING COUNT(*) > 1 "
            "ORDER BY split_origin_invitation_id"
        )
    ).scalars()
    return [str(value) for value in rows]


def _apply(bind) -> None:
    """Create the partial-UNIQUE index, failing loud on legacy duplicates.

    Split out from :func:`upgrade` (which only supplies ``op.get_bind()``) so
    the migration test can drive it against a plain connection.
    """
    if not _has_table(bind, "expenses"):
        return
    # Fresh DBs build the index from ``Base.metadata`` via create_all before
    # Alembic replays from baseline; skip (and skip the dup scan) if present.
    if _has_index(bind, "expenses", INDEX_NAME):
        return

    duplicates = _duplicate_split_origins(bind)
    if duplicates:
        raise RuntimeError(
            "无法创建 uq_expenses_split_origin_invitation：检测到 "
            f"{len(duplicates)} 个 invitation 已有重复 received 支出（旧并发 accept "
            "竞态遗留）。这是钱，迁移不会自动删除。请人工裁定每个 invitation 保留哪一"
            "笔、驳回/删除多余支出后重跑迁移。受影响 invitation public_id："
            f"{', '.join(duplicates)}"
        )

    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_expenses_split_origin_invitation "
            "ON expenses (split_origin_invitation_id) "
            "WHERE split_origin_invitation_id IS NOT NULL"
        )
    )


def upgrade() -> None:
    _apply(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "expenses") and _has_index(bind, "expenses", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="expenses")
