"""add member repayment proposals table (ADR-0049 slice 3).

Revision ID: 20260614_0002
Revises: 20260614_0001
Create Date: 2026-06-14

ADR-0049 Slice 3: the debtor-side ``member_repayment_proposals`` table — the
pending "I paid" intent for a member Debt (§3.2). The ORM declares the model, so
a fresh ``Base.metadata.create_all`` (the legacy-to-alembic bridge ``init_db()``
runs before ``alembic upgrade head``) already has the table — the ``create_table``
is guarded so the revision stays idempotent in that case, same shape as
20260614_0001. On the pure-Alembic path (a Postgres DB advanced by Alembic alone)
this creates the table + CHECK / FK / PK / UNIQUE + indexes, including the
``uq_mrp_one_pending_per_debt`` partial UNIQUE index (``WHERE status = 'pending'``,
the §3.2 one-pending-per-Debt backstop). The partial predicate text is, by manual
convention, kept byte-identical to the ORM ``postgresql_where``; the
``_audit_partial_index_pg_where`` lane only checks that a partial UNIQUE declares
``postgresql_where`` at all (so it does not silently degrade to a whole-table
UNIQUE on PostgreSQL) — it does not diff the predicate text.

Additive only: no existing column/table is touched, so there is no backfill or
constraint-tightening step. ``downgrade()`` drops the table (its indexes drop
with it).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260614_0002"
down_revision: str | Sequence[str] | None = "20260614_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_member_repayment_proposals() -> None:
    op.create_table(
        "member_repayment_proposals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("debt_id", sa.Integer(), nullable=False),
        sa.Column("debtor_account_id", sa.Integer(), nullable=False),
        sa.Column("creditor_account_id", sa.Integer(), nullable=False),
        sa.Column("proposed_by_account_id", sa.Integer(), nullable=False),
        sa.Column("proposed_amount_cents", sa.Integer(), nullable=False),
        sa.Column("home_currency_code", sa.String(length=3), nullable=False),
        sa.Column("original_currency_code", sa.String(length=3), nullable=True),
        sa.Column("original_amount_minor", sa.Integer(), nullable=True),
        sa.Column("exchange_rate_to_cny", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("exchange_rate_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exchange_rate_source", sa.String(length=32), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("confirmed_amount_cents", sa.Integer(), nullable=True),
        sa.Column("committed_repayment_id", sa.Integer(), nullable=True),
        sa.Column("supersedes_proposal_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_account_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "proposed_amount_cents > 0",
            name="ck_member_repayment_proposals_amount_positive",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'partially_confirmed', "
            "'rejected', 'withdrawn', 'expired', 'superseded')",
            name="ck_member_repayment_proposals_status_valid",
        ),
        sa.CheckConstraint(
            "length(home_currency_code) = 3", name="ck_mrp_home_currency_format"
        ),
        sa.ForeignKeyConstraint(
            ["debt_id"], ["debts.id"], name="fk_member_repayment_proposals_debt"
        ),
        sa.ForeignKeyConstraint(
            ["debtor_account_id"], ["accounts.id"], name="fk_mrp_debtor_account"
        ),
        sa.ForeignKeyConstraint(
            ["creditor_account_id"], ["accounts.id"], name="fk_mrp_creditor_account"
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_account_id"], ["accounts.id"], name="fk_mrp_proposed_by_account"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_account_id"], ["accounts.id"], name="fk_mrp_resolved_by_account"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    with op.batch_alter_table("member_repayment_proposals", schema=None) as batch_op:
        # The two plain-column indexes use the ORM ``index=True`` auto-generated
        # names (``ix_<table>_<column>``) so ``create_all`` (legacy bridge) and
        # this Alembic path declare the SAME index name, matching the slice-1
        # convention (``ix_debts_public_id`` / ``ix_repayments_debt_id``).
        batch_op.create_index(
            "ix_member_repayment_proposals_public_id", ["public_id"], unique=True
        )
        batch_op.create_index(
            "ix_member_repayment_proposals_debt_id", ["debt_id"], unique=False
        )
        # ``ix_mrp_debt_status`` carries an explicit matching name in both the ORM
        # ``Index(...)`` and here, so it is not auto-named.
        batch_op.create_index("ix_mrp_debt_status", ["debt_id", "status"], unique=False)
    # §3.2 one-pending-per-Debt backstop. The partial predicate text is, by manual
    # convention, kept byte-identical to the ORM
    # ``postgresql_where=text("status = 'pending'")`` (the ``_audit_partial_index_pg_where``
    # lane only flags a missing ``postgresql_where``, it does not compare predicate
    # text — see the ORM comment).
    op.create_index(
        "uq_mrp_one_pending_per_debt",
        "member_repayment_proposals",
        ["debt_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "member_repayment_proposals" in existing:
        return
    _create_member_repayment_proposals()


def downgrade() -> None:
    op.drop_table("member_repayment_proposals")
