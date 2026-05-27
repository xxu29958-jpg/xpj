"""add pending bill split invitation uniqueness.

Revision ID: 9d8a7c6b5e4f
Revises: bb00c453bf29
Create Date: 2026-05-28

ADR-0029 allows only one active ``invited`` row for a
``(sender_expense_id, receiver_account_id)`` pair. The service keeps a
fast-path pre-check for user-facing errors, but this partial UNIQUE index is
the concurrency authority.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d8a7c6b5e4f"
down_revision: str | Sequence[str] | None = "bb00c453bf29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_bill_split_invitations_pending_receiver"


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(bind).get_indexes(table_name)
    )


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _pending_duplicate(bind):
    return bind.execute(
        sa.text(
            "SELECT sender_expense_id, receiver_account_id, COUNT(*) AS count "
            "FROM bill_split_invitations "
            "WHERE status = 'invited' "
            "GROUP BY sender_expense_id, receiver_account_id "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).mappings().first()


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "bill_split_invitations"):
        return

    duplicate = _pending_duplicate(bind)
    if duplicate is not None:
        raise RuntimeError(
            "Invalid legacy data: bill_split_invitations contains duplicate "
            "pending invitations for "
            f"sender_expense_id={duplicate['sender_expense_id']} "
            f"receiver_account_id={duplicate['receiver_account_id']}"
        )

    if not _has_index(bind, "bill_split_invitations", INDEX_NAME):
        bind.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_bill_split_invitations_pending_receiver "
                "ON bill_split_invitations "
                "(sender_expense_id, receiver_account_id) "
                "WHERE status = 'invited'"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "bill_split_invitations") and _has_index(
        bind,
        "bill_split_invitations",
        INDEX_NAME,
    ):
        op.drop_index(INDEX_NAME, table_name="bill_split_invitations")
