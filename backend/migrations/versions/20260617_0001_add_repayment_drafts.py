"""add repayment_drafts (NLS-captured repayment review inbox).

Revision ID: 20260617_0001
Revises: 20260616_0002
Create Date: 2026-06-17

ADR-0049 §杠杆③ (slice 3a): the ``RepaymentDraft`` holding table for an NLS-captured
repayment awaiting human review. A repayment notification ("还款成功" / "自动扣款") for
an external revolving debt (花呗 / 借呗 / 白条 / 京东 / 美团月付 / 银行卡) lands here as a
PENDING draft; the user confirms it against a chosen open external/manual Debt (records
one ``Repayment``) or dismisses it (§8 — never auto-recorded).

The ORM declares the model, so a fresh ``Base.metadata.create_all`` (the bridge
``init_db()`` runs before ``alembic upgrade head``) already has the table — the
``create_table`` is guarded so the revision stays a no-op in that case, same shape as
20260614_0001 / 20260616_0001. On the pure-Alembic path this creates the table + CHECKs
/ FKs / indexes so the schema matches ``create_all``.

Additive only: no existing column/table is touched. Dedup uniqueness is the per-tenant
``uq_repayment_drafts_idem`` (tenant_id + draft_idempotency_key) — the content+identity
hash that makes a re-posted notification a no-op rather than a twin draft.
``downgrade()`` drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260617_0001"
down_revision: str | Sequence[str] | None = "20260616_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_repayment_drafts() -> None:
    op.create_table(
        "repayment_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("home_currency_code", sa.String(length=3), nullable=False),
        sa.Column("merchant_label", sa.String(length=255), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("committed_debt_public_id", sa.String(length=36), nullable=True),
        sa.Column("committed_repayment_public_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_account_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_repayment_drafts_amount_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'dismissed')",
            name="ck_repayment_drafts_status_valid",
        ),
        sa.CheckConstraint(
            "length(home_currency_code) = 3", name="ck_repayment_drafts_home_currency_format"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["ledgers.ledger_id"], name="fk_repayment_drafts_tenant_ledger"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["accounts.id"],
            name="fk_repayment_drafts_created_by_account",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_account_id"],
            ["accounts.id"],
            name="fk_repayment_drafts_resolved_by_account",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "tenant_id", "draft_idempotency_key", name="uq_repayment_drafts_idem"
        ),
    )
    with op.batch_alter_table("repayment_drafts", schema=None) as batch_op:
        batch_op.create_index("ix_repayment_drafts_public_id", ["public_id"], unique=True)
        batch_op.create_index("ix_repayment_drafts_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index(
            "ix_repayment_drafts_tenant_status", ["tenant_id", "status"], unique=False
        )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "repayment_drafts" not in existing:
        _create_repayment_drafts()


def downgrade() -> None:
    op.drop_table("repayment_drafts")
