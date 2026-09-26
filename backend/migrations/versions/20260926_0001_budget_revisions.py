"""Preserve saved budget arrangements without inventing pre-existing history.

Revision ID: 20260926_0001
Revises: 20260920_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20260926_0001"
down_revision = "20260920_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_budgets_id_tenant", "budgets", ["id", "tenant_id"])
    op.create_table("budget_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("budget_id", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["budget_id", "tenant_id"], ["budgets.id", "budgets.tenant_id"],
            name="fk_budget_revision_budget_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], name="fk_budget_revision_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "budget_id", "row_version", name="uq_budget_revision_version"),
        sa.CheckConstraint("row_version >= 1", name="ck_budget_revision_version"),
        sa.CheckConstraint("change_kind IN ('baseline', 'create', 'edit', 'archive', 'restore')", name="ck_budget_revision_kind"))
    op.execute("""
        INSERT INTO budget_revisions (tenant_id, budget_id, row_version, change_kind, snapshot, recorded_at)
        SELECT b.tenant_id, b.id, b.row_version, 'baseline', json_build_object(
            'home_currency_code', b.home_currency_code, 'total_amount_cents', b.total_amount_cents,
            'non_monthly_amount_cents', b.non_monthly_amount_cents, 'rollover_amount_cents', b.rollover_amount_cents,
            'excluded_categories', b.excluded_categories::json, 'archived', b.archived_at IS NOT NULL,
            'category_budgets', COALESCE((SELECT json_agg(json_build_object(
                'category', c.category, 'amount_cents', c.amount_cents) ORDER BY c.category, c.id)
                FROM budget_categories c WHERE c.tenant_id = b.tenant_id AND c.month = b.month), '[]'::json)
        ), CURRENT_TIMESTAMP FROM budgets b
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_budget_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'budget revisions are immutable' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER trg_budget_revision_immutable BEFORE UPDATE OR DELETE ON budget_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_budget_revision_immutable();
    """)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM budget_revisions WHERE change_kind <> 'baseline')")):
        raise RuntimeError("cannot erase recorded budget revisions")
    op.drop_table("budget_revisions")
    op.execute("DROP FUNCTION ticketbox_budget_revision_immutable()")
    op.drop_constraint("uq_budgets_id_tenant", "budgets", type_="unique")
