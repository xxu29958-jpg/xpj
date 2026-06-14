"""add debt domain tables (debts + 4 append-only fact tables).

Revision ID: 20260614_0001
Revises: 20260606_0001
Create Date: 2026-06-14

ADR-0049 Slice 1: the Debt obligation parent (``debts``) plus the four
append-only fact tables (``repayments`` / ``debt_adjustments`` /
``repayment_voids`` / ``debt_voids``). The ORM declares all five models, so a
fresh ``Base.metadata.create_all`` (the legacy-to-alembic bridge ``init_db()``
runs before ``alembic upgrade head``) already has the tables — each
``create_table`` is guarded so the revision stays idempotent in that case, same
shape as 20260603_0002 (api_idempotency_keys). On the pure-Alembic path
(a Postgres DB advanced by Alembic alone) this creates the tables + CHECK / FK /
indexes so the schema matches ``create_all``.

Additive only: no existing column/table is touched, so there is no backfill or
constraint-tightening step. ``downgrade()`` drops the tables in reverse FK order
(fact tables before ``debts``; ``repayment_voids`` before ``repayments``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260614_0001"
down_revision: str | Sequence[str] | None = "20260606_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_debts() -> None:
    op.create_table(
        "debts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("counterparty_type", sa.String(length=16), nullable=False),
        sa.Column("counterparty_account_id", sa.Integer(), nullable=True),
        sa.Column("counterparty_label", sa.String(length=255), nullable=True),
        sa.Column("principal_amount_cents", sa.Integer(), nullable=False),
        sa.Column("home_currency_code", sa.String(length=3), nullable=False),
        sa.Column("original_currency_code", sa.String(length=3), nullable=True),
        sa.Column("original_amount_minor", sa.Integer(), nullable=True),
        sa.Column("exchange_rate_to_cny", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("exchange_rate_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exchange_rate_source", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("direction IN ('i_owe', 'owed_to_me')", name="ck_debts_direction_valid"),
        sa.CheckConstraint(
            "counterparty_type IN ('member', 'external')",
            name="ck_debts_counterparty_type_valid",
        ),
        sa.CheckConstraint("status IN ('open', 'cleared', 'voided')", name="ck_debts_status_valid"),
        sa.CheckConstraint(
            "source_type IN ('manual', 'bill_split')", name="ck_debts_source_type_valid"
        ),
        sa.CheckConstraint("principal_amount_cents > 0", name="ck_debts_principal_positive"),
        sa.CheckConstraint("length(home_currency_code) = 3", name="ck_debts_home_currency_format"),
        sa.ForeignKeyConstraint(["tenant_id"], ["ledgers.ledger_id"], name="fk_debts_tenant_ledger"),
        sa.ForeignKeyConstraint(["owner_account_id"], ["accounts.id"], name="fk_debts_owner_account"),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"], ["accounts.id"], name="fk_debts_created_by_account"
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_account_id"], ["accounts.id"], name="fk_debts_counterparty_account"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_debts_source"),
    )
    with op.batch_alter_table("debts", schema=None) as batch_op:
        batch_op.create_index("ix_debts_public_id", ["public_id"], unique=True)
        batch_op.create_index("ix_debts_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index("ix_debts_owner_account_id", ["owner_account_id"], unique=False)
        batch_op.create_index("ix_debts_tenant_status", ["tenant_id", "status"], unique=False)
        batch_op.create_index(
            "ix_debts_tenant_owner_direction",
            ["tenant_id", "owner_account_id", "direction"],
            unique=False,
        )
        batch_op.create_index(
            "ix_debts_tenant_public_id", ["tenant_id", "public_id"], unique=False
        )


def _create_repayments() -> None:
    op.create_table(
        "repayments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("debt_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("original_currency_code", sa.String(length=3), nullable=True),
        sa.Column("original_amount_minor", sa.Integer(), nullable=True),
        sa.Column("exchange_rate_to_cny", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("exchange_rate_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exchange_rate_source", sa.String(length=32), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_repayments_amount_positive"),
        sa.ForeignKeyConstraint(["debt_id"], ["debts.id"], name="fk_repayments_debt"),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], name="fk_repayments_actor_account"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    with op.batch_alter_table("repayments", schema=None) as batch_op:
        batch_op.create_index("ix_repayments_public_id", ["public_id"], unique=True)
        batch_op.create_index("ix_repayments_debt_id", ["debt_id"], unique=False)
        batch_op.create_index(
            "ix_repayments_debt_created", ["debt_id", "created_at"], unique=False
        )


def _create_debt_adjustments() -> None:
    op.create_table(
        "debt_adjustments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("debt_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["debt_id"], ["debts.id"], name="fk_debt_adjustments_debt"),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], name="fk_debt_adjustments_actor_account"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    with op.batch_alter_table("debt_adjustments", schema=None) as batch_op:
        batch_op.create_index("ix_debt_adjustments_public_id", ["public_id"], unique=True)
        batch_op.create_index("ix_debt_adjustments_debt_id", ["debt_id"], unique=False)
        batch_op.create_index(
            "ix_debt_adjustments_debt_created", ["debt_id", "created_at"], unique=False
        )


def _create_repayment_voids() -> None:
    op.create_table(
        "repayment_voids",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("repayment_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repayment_id"], ["repayments.id"], name="fk_repayment_voids_repayment"
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], name="fk_repayment_voids_actor_account"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("repayment_id", name="uq_repayment_voids_repayment"),
    )
    with op.batch_alter_table("repayment_voids", schema=None) as batch_op:
        batch_op.create_index("ix_repayment_voids_public_id", ["public_id"], unique=True)
        batch_op.create_index("ix_repayment_voids_repayment_id", ["repayment_id"], unique=False)


def _create_debt_voids() -> None:
    op.create_table(
        "debt_voids",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("debt_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["debt_id"], ["debts.id"], name="fk_debt_voids_debt"),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], name="fk_debt_voids_actor_account"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("debt_id", name="uq_debt_voids_debt"),
    )
    with op.batch_alter_table("debt_voids", schema=None) as batch_op:
        batch_op.create_index("ix_debt_voids_public_id", ["public_id"], unique=True)
        batch_op.create_index("ix_debt_voids_debt_id", ["debt_id"], unique=False)


# Guarded create order: parent ``debts`` first, then facts that FK it;
# ``repayment_voids`` FKs ``repayments`` so it follows that table.
_TABLE_BUILDERS = (
    ("debts", _create_debts),
    ("repayments", _create_repayments),
    ("debt_adjustments", _create_debt_adjustments),
    ("repayment_voids", _create_repayment_voids),
    ("debt_voids", _create_debt_voids),
)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name, builder in _TABLE_BUILDERS:
        if name in existing:
            continue
        builder()


def downgrade() -> None:
    # Reverse FK dependency order: drop fact tables (and repayment_voids before
    # repayments) before the parent ``debts``.
    op.drop_table("debt_voids")
    op.drop_table("repayment_voids")
    op.drop_table("debt_adjustments")
    op.drop_table("repayments")
    op.drop_table("debts")
