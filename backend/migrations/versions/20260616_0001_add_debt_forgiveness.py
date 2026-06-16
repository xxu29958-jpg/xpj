"""add debt_forgivenesses (creditor waiver append-only fact).

Revision ID: 20260616_0001
Revises: 20260615_0001
Create Date: 2026-06-16

ADR-0049 §3.7 / §4 (slice 8e-3): the ``DebtForgiveness`` append-only fact backing
the creditor "算了，不用还了" waiver. The ORM declares the model, so a fresh
``Base.metadata.create_all`` (the bridge ``init_db()`` runs before ``alembic upgrade
head``) already has the table — the ``create_table`` is guarded so the revision stays
a no-op in that case, same shape as 20260614_0001. On the pure-Alembic path this
creates the table + CHECK / FK / indexes so the schema matches ``create_all``.

Additive only: no existing column/table is touched. There is NO global
``UNIQUE(idempotency_key)`` (uniqueness is tenant-scoped in ``api_idempotency_keys``
per §3.6 — the same scope fix 20260614_0003 applied to the slice-1 fact tables).
``downgrade()`` drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260616_0001"
down_revision: str | Sequence[str] | None = "20260615_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_debt_forgivenesses() -> None:
    op.create_table(
        "debt_forgivenesses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("debt_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_debt_forgivenesses_amount_positive"),
        sa.ForeignKeyConstraint(["debt_id"], ["debts.id"], name="fk_debt_forgivenesses_debt"),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], name="fk_debt_forgivenesses_actor_account"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    with op.batch_alter_table("debt_forgivenesses", schema=None) as batch_op:
        batch_op.create_index("ix_debt_forgivenesses_public_id", ["public_id"], unique=True)
        batch_op.create_index("ix_debt_forgivenesses_debt_id", ["debt_id"], unique=False)
        batch_op.create_index(
            "ix_debt_forgivenesses_debt_created", ["debt_id", "created_at"], unique=False
        )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "debt_forgivenesses" not in existing:
        _create_debt_forgivenesses()


def downgrade() -> None:
    op.drop_table("debt_forgivenesses")
