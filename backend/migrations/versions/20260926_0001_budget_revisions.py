"""Preserve saved budget arrangements without inventing pre-existing history.

Revision ID: 20260926_0001
Revises: 20260920_0003
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260926_0001"
down_revision = "20260920_0003"
branch_labels = None
depends_on = None


def _baseline_exclusions(value):
    """Freeze the parent reader's tolerant semantics; do not rewrite its raw TEXT."""
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    normalized = []
    for item in parsed:
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= 64:
            continue
        category = {"吃饭": "餐饮"}.get(item.strip(), item.strip())
        if category not in normalized:
            normalized.append(category)
    return normalized


def _capture_baselines(bind):
    rows = bind.execute(sa.text("""
        SELECT b.tenant_id, b.id AS budget_id, b.row_version, b.excluded_categories,
        json_build_object(
            'home_currency_code', b.home_currency_code, 'total_amount_cents', b.total_amount_cents,
            'non_monthly_amount_cents', b.non_monthly_amount_cents, 'rollover_amount_cents', b.rollover_amount_cents,
            'archived', b.archived_at IS NOT NULL,
            'category_budgets', COALESCE((SELECT json_agg(json_build_object(
                'category', c.category, 'amount_cents', c.amount_cents) ORDER BY c.category, c.id)
                FROM budget_categories c WHERE c.tenant_id = b.tenant_id AND c.month = b.month), '[]'::json)
        ) AS snapshot FROM budgets b
    """)).mappings()
    insert = sa.text("""
        INSERT INTO budget_revisions (tenant_id, budget_id, row_version, change_kind, snapshot, recorded_at)
        VALUES (:tenant_id, :budget_id, :row_version, 'baseline', :snapshot, CURRENT_TIMESTAMP)
    """).bindparams(sa.bindparam("snapshot", type_=sa.JSON()))
    for batch in rows.partitions(100):
        payloads = []
        for row in batch:
            snapshot = row["snapshot"]
            snapshot["excluded_categories"] = _baseline_exclusions(row["excluded_categories"])
            payloads.append({"tenant_id": row["tenant_id"], "budget_id": row["budget_id"],
                "row_version": row["row_version"], "snapshot": snapshot})
        bind.execute(insert, payloads)


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the budget history edge")


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
    _capture_baselines(op.get_bind())
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_budget_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'budget revisions are immutable' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER trg_budget_revision_immutable BEFORE UPDATE OR DELETE ON budget_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_budget_revision_immutable();
    """)
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM budget_revisions WHERE change_kind <> 'baseline')")):
        raise RuntimeError("cannot erase recorded budget revisions")
    op.drop_table("budget_revisions")
    op.execute("DROP FUNCTION ticketbox_budget_revision_immutable()")
    op.drop_constraint("uq_budgets_id_tenant", "budgets", type_="unique")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("budget_revisions")}
    required = {"id", "tenant_id", "budget_id", "row_version", "change_kind", "snapshot", "recorded_at"}
    if not required <= columns.keys() or any(columns[name]["nullable"] for name in required):
        raise RuntimeError("budget history is missing required snapshot fields")
    if not isinstance(columns["snapshot"]["type"], sa.JSON):
        raise RuntimeError("budget history must preserve structured snapshots")
    timestamp = columns["recorded_at"]["type"]
    if not isinstance(timestamp, sa.DateTime) or not timestamp.timezone:
        raise RuntimeError("budget history recording time must include timezone")
    unique_keys = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("budget_revisions")}
    if ("tenant_id", "budget_id", "row_version") not in unique_keys:
        raise RuntimeError("budget history must record each saved version once")
    parent_keys = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("budgets")}
    if ("id", "tenant_id") not in parent_keys:
        raise RuntimeError("budget history parent identity is missing")
    foreign_keys = inspector.get_foreign_keys("budget_revisions")
    if not any(item["constrained_columns"] == ["budget_id", "tenant_id"]
               and item["referred_table"] == "budgets" and item["referred_columns"] == ["id", "tenant_id"]
               and item["options"].get("ondelete") == "RESTRICT" for item in foreign_keys):
        raise RuntimeError("budget history must retain its original ledger and budget")
    checks = {item["name"] for item in inspector.get_check_constraints("budget_revisions")}
    if not {"ck_budget_revision_version", "ck_budget_revision_kind"} <= checks:
        raise RuntimeError("budget history version and change guards are missing")
    triggers = set(bind.scalars(sa.text(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'budget_revisions'::regclass "
        "AND NOT tgisinternal AND tgenabled = 'O'"
    )))
    if "trg_budget_revision_immutable" not in triggers:
        raise RuntimeError("budget history immutability guard is missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with budget history")
