"""Preserve known spending definitions without reconstructing unknown old edits.

Revision ID: 20260927_0002
Revises: 20260927_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0002"
down_revision = "20260927_0001"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the spending goal history edge")


def upgrade() -> None:
    op.create_unique_constraint("uq_goals_id_tenant", "goals", ["id", "tenant_id"])
    op.create_table("goal_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["goal_id", "tenant_id"], ["goals.id", "goals.tenant_id"],
            name="fk_goal_revision_goal_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], name="fk_goal_revision_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "goal_id", "row_version", name="uq_goal_revision_version"),
        sa.CheckConstraint("row_version >= 1", name="ck_goal_revision_version"),
        sa.CheckConstraint("change_kind IN ('baseline', 'create', 'edit', 'archive', 'restore')", name="ck_goal_revision_kind"),
        sa.CheckConstraint("snapshot ->> 'goal_type' = 'spending_limit'", name="ck_goal_revision_spending_type"))
    op.execute("""
        INSERT INTO goal_revisions (tenant_id, goal_id, row_version, change_kind, snapshot, recorded_at)
        SELECT tenant_id, id, row_version, 'baseline', json_build_object(
            'name', name, 'goal_type', goal_type, 'period', period, 'month', month, 'category', category,
            'target_amount_cents', target_amount_cents, 'home_currency_code', home_currency_code, 'status', status
        ), CURRENT_TIMESTAMP FROM goals WHERE goal_type = 'spending_limit'
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_goal_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'goal revisions are immutable' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER trg_goal_revision_immutable BEFORE UPDATE OR DELETE ON goal_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_goal_revision_immutable();
    """)
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM goal_revisions WHERE change_kind <> 'baseline')")):
        raise RuntimeError("cannot erase recorded goal revisions")
    op.drop_table("goal_revisions")
    op.execute("DROP FUNCTION ticketbox_goal_revision_immutable()")
    op.drop_constraint("uq_goals_id_tenant", "goals", type_="unique")
    _set_authority_revision(bind, revision, down_revision)


def _assert_snapshot_shape(inspector):
    columns = {column["name"]: column for column in inspector.get_columns("goal_revisions")}
    required = {"id", "tenant_id", "goal_id", "row_version", "change_kind", "snapshot", "recorded_at"}
    if not required <= columns.keys() or any(columns[name]["nullable"] for name in required):
        raise RuntimeError("goal history is missing required snapshot fields")
    if not isinstance(columns["snapshot"]["type"], sa.JSON):
        raise RuntimeError("goal history must preserve structured snapshots")
    timestamp = columns["recorded_at"]["type"]
    if not isinstance(timestamp, sa.DateTime) or not timestamp.timezone:
        raise RuntimeError("goal history recording time must include timezone")
    checks = {item["name"] for item in inspector.get_check_constraints("goal_revisions")}
    if not {"ck_goal_revision_version", "ck_goal_revision_kind", "ck_goal_revision_spending_type"} <= checks:
        raise RuntimeError("goal history version and definition guards are missing")


def _assert_history_identity(inspector):
    keys = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("goal_revisions")}
    if ("tenant_id", "goal_id", "row_version") not in keys:
        raise RuntimeError("goal history must record each accepted version once")
    parent_keys = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("goals")}
    if ("id", "tenant_id") not in parent_keys:
        raise RuntimeError("goal history parent identity is missing")
    if not any(item["constrained_columns"] == ["goal_id", "tenant_id"]
        and item["referred_table"] == "goals" and item["referred_columns"] == ["id", "tenant_id"]
        and item["options"].get("ondelete") == "RESTRICT"
        for item in inspector.get_foreign_keys("goal_revisions")):
        raise RuntimeError("goal history must retain its original ledger and goal")


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    _assert_snapshot_shape(inspector)
    _assert_history_identity(inspector)
    triggers = set(bind.scalars(sa.text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'goal_revisions'::regclass "
        "AND NOT tgisinternal AND tgenabled = 'O'")))
    if "trg_goal_revision_immutable" not in triggers:
        raise RuntimeError("goal history immutability guard is missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with goal history")
