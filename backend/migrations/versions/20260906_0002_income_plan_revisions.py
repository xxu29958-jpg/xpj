"""Keep declared income month revisions without inventing legacy history."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0002"
down_revision = "20260906_0001"
branch_labels = None
depends_on = None

_TABLE = "income_plan_revisions"


def _create_revisions():
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("effective_month", sa.Date(), nullable=True),
        sa.Column("intent_month", sa.Date(), nullable=True),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("income_month", sa.String(7), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("pay_day", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id", "tenant_id"], ["monthly_income_plans.id", "monthly_income_plans.tenant_id"],
            name="fk_income_plan_revision_plan_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], name="fk_income_plan_revision_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "plan_id", "revision_number", name="uq_income_plan_revision_number"),
        sa.CheckConstraint("revision_number >= 1", name="ck_income_plan_revision_number"),
        sa.CheckConstraint(
            "(effective_month IS NULL OR EXTRACT(DAY FROM effective_month) = 1) AND "
            "(intent_month IS NULL OR EXTRACT(DAY FROM intent_month) = 1)", name="ck_income_plan_revision_month",
        ),
        sa.CheckConstraint("amount_cents BETWEEN 0 AND 9000000000000", name="ck_income_plan_revision_money"),
        sa.CheckConstraint("pay_day BETWEEN 1 AND 31", name="ck_income_plan_revision_pay_day"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_income_plan_revision_status"),
        sa.CheckConstraint(
            "(frequency = 'monthly' AND income_month IS NULL) OR "
            "(frequency = 'one_time' AND income_month IS NOT NULL)",
            name="ck_income_plan_revision_frequency",
        ),
        sa.CheckConstraint(
            "change_kind IN ('baseline', 'create', 'edit', 'archive', 'restore') AND "
            "((change_kind = 'baseline' AND effective_month IS NULL AND intent_month IS NULL) OR "
            "(change_kind <> 'baseline' AND effective_month IS NOT NULL AND intent_month IS NOT NULL))",
            name="ck_income_plan_revision_kind",
        ),
    )


def _set_authority_revision(bind, expected, target):
    updated = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority is outside the income revision migration edge")


def upgrade():
    bind = op.get_bind()
    uniques = {entry["name"] for entry in sa.inspect(bind).get_unique_constraints("monthly_income_plans")}
    if "uq_income_plan_id_tenant" not in uniques:
        op.create_unique_constraint("uq_income_plan_id_tenant", "monthly_income_plans", ["id", "tenant_id"])
    if not sa.inspect(bind).has_table(_TABLE):
        _create_revisions()
    op.execute("""
        INSERT INTO income_plan_revisions (
            tenant_id, plan_id, revision_number, effective_month, change_kind,
            label, source_type, frequency, income_month, amount_cents, pay_day, status, recorded_at
        ) SELECT tenant_id, id, row_version, NULL, 'baseline', label, source_type,
            frequency, income_month, amount_cents, pay_day, status, CURRENT_TIMESTAMP
          FROM monthly_income_plans AS plan
          WHERE NOT EXISTS (SELECT 1 FROM income_plan_revisions AS revision
                            WHERE revision.plan_id = plan.id AND revision.tenant_id = plan.tenant_id)
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_income_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'income plan revisions are immutable' USING ERRCODE = '55000';
        END $$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_income_plan_revision_immutable ON income_plan_revisions")
    op.execute("""
        CREATE TRIGGER trg_income_plan_revision_immutable
        BEFORE UPDATE OR DELETE ON income_plan_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_income_revision_immutable()
    """)
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM income_plan_revisions)")):
        raise RuntimeError("cannot downgrade while income plan revision history exists")
    op.drop_table(_TABLE)
    op.execute("DROP FUNCTION ticketbox_income_revision_immutable()")
    op.drop_constraint("uq_income_plan_id_tenant", "monthly_income_plans", type_="unique")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    if not sa.inspect(bind).has_table(_TABLE):
        raise RuntimeError("income plan revision schema is missing")
    trigger = bind.scalar(sa.text(
        "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_income_plan_revision_immutable' "
        "AND tgrelid = 'income_plan_revisions'::regclass AND tgenabled = 'O'"
    ))
    if trigger != 1:
        raise RuntimeError("income plan revision history is not immutable")
    live_revision = bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_revision = revision if live_revision == down_revision else live_revision
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1"))
    if authority != expected_revision:
        raise RuntimeError("dataset authority is not aligned with income plan revision schema")
