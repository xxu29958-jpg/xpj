"""Capture known current series definitions; old occurrence bases remain unknown.

Revision ID: 20260927_0003
Revises: 20260927_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0003"
down_revision = "20260927_0002"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the recurring definition history edge")


def upgrade() -> None:
    op.create_table("recurring_item_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["series_id", "tenant_id"], ["recurring_items.id", "recurring_items.tenant_id"],
            name="fk_recurring_item_revision_series_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], name="fk_recurring_item_revision_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("series_id", "tenant_id", "row_version", name="uq_recurring_item_revision_version"),
        sa.CheckConstraint("row_version >= 1", name="ck_recurring_item_revision_version"),
        sa.CheckConstraint("change_kind IN ('baseline', 'create', 'edit', 'pause', 'resume', 'archive', 'restore')",
            name="ck_recurring_item_revision_kind"))
    op.execute("""
        INSERT INTO recurring_item_revisions (tenant_id, series_id, row_version, change_kind, snapshot, recorded_at)
        SELECT tenant_id, id, row_version, 'baseline', json_build_object(
            'merchant', merchant_name, 'merchant_key', merchant_key, 'frequency', frequency,
            'home_currency_code', home_currency_code, 'baseline_amount_cents', baseline_amount_cents,
            'next_expected_date', next_expected_date, 'status', status, 'source', source
        ), CURRENT_TIMESTAMP FROM recurring_items
    """)
    op.add_column("recurring_occurrences", sa.Column("recorded_definition_row_version", sa.Integer(), nullable=True))
    op.add_column("recurring_occurrences", sa.Column("definition_recorded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_recurring_occurrence_recorded_definition", "recurring_occurrences", "recurring_item_revisions",
        ["series_id", "tenant_id", "recorded_definition_row_version"], ["series_id", "tenant_id", "row_version"], ondelete="RESTRICT")
    op.create_check_constraint("ck_recurring_occurrence_recorded_definition", "recurring_occurrences",
        "(recorded_definition_row_version IS NULL) = (definition_recorded_at IS NULL)")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_recurring_item_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'recurring item revisions are immutable' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER trg_recurring_item_revision_immutable BEFORE UPDATE OR DELETE ON recurring_item_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_recurring_item_revision_immutable();
        CREATE OR REPLACE FUNCTION ticketbox_recurring_occurrence_definition_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.recorded_definition_row_version IS DISTINCT FROM OLD.recorded_definition_row_version
               OR NEW.definition_recorded_at IS DISTINCT FROM OLD.definition_recorded_at THEN
                RAISE EXCEPTION 'recorded recurring definitions are immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_recurring_occurrence_definition_immutable BEFORE UPDATE ON recurring_occurrences
        FOR EACH ROW EXECUTE FUNCTION ticketbox_recurring_occurrence_definition_immutable();
    """)
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM recurring_item_revisions WHERE change_kind <> 'baseline')")) \
        or bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM recurring_occurrences WHERE recorded_definition_row_version IS NOT NULL)")):
        raise RuntimeError("cannot erase recorded recurring definitions")
    op.execute("DROP TRIGGER trg_recurring_occurrence_definition_immutable ON recurring_occurrences")
    op.execute("DROP FUNCTION ticketbox_recurring_occurrence_definition_immutable()")
    op.drop_constraint("fk_recurring_occurrence_recorded_definition", "recurring_occurrences", type_="foreignkey")
    op.drop_constraint("ck_recurring_occurrence_recorded_definition", "recurring_occurrences", type_="check")
    op.drop_column("recurring_occurrences", "definition_recorded_at")
    op.drop_column("recurring_occurrences", "recorded_definition_row_version")
    op.drop_table("recurring_item_revisions")
    op.execute("DROP FUNCTION ticketbox_recurring_item_revision_immutable()")
    _set_authority_revision(bind, revision, down_revision)


def _assert_revision_shape(inspector):
    columns = {column["name"]: column for column in inspector.get_columns("recurring_item_revisions")}
    required = {"id", "tenant_id", "series_id", "row_version", "change_kind", "snapshot", "recorded_at"}
    if not required <= columns.keys() or any(columns[name]["nullable"] for name in required):
        raise RuntimeError("recurring history is missing required definition fields")
    if not isinstance(columns["snapshot"]["type"], sa.JSON):
        raise RuntimeError("recurring history must preserve structured definitions")
    timestamp = columns["recorded_at"]["type"]
    if not isinstance(timestamp, sa.DateTime) or not timestamp.timezone:
        raise RuntimeError("recurring history recording time must include timezone")
    keys = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("recurring_item_revisions")}
    if ("series_id", "tenant_id", "row_version") not in keys:
        raise RuntimeError("recurring history must record each accepted version once")
    checks = {item["name"] for item in inspector.get_check_constraints("recurring_item_revisions")}
    if not {"ck_recurring_item_revision_version", "ck_recurring_item_revision_kind"} <= checks:
        raise RuntimeError("recurring history version and change guards are missing")


def _assert_occurrence_basis(inspector):
    columns = {column["name"]: column for column in inspector.get_columns("recurring_occurrences")}
    for column in ("recorded_definition_row_version", "definition_recorded_at"):
        if column not in columns or not columns[column]["nullable"]:
            raise RuntimeError("old occurrence definition evidence must remain explicitly unknown")
    timestamp = columns["definition_recorded_at"]["type"]
    if not isinstance(timestamp, sa.DateTime) or not timestamp.timezone:
        raise RuntimeError("occurrence recording time must include timezone")
    checks = {item["name"] for item in inspector.get_check_constraints("recurring_occurrences")}
    if "ck_recurring_occurrence_recorded_definition" not in checks:
        raise RuntimeError("occurrence definition evidence must be complete or unknown")


def _assert_parent_guards(inspector):
    references = (("recurring_item_revisions", ["series_id", "tenant_id"], "recurring_items", ["id", "tenant_id"]),
        ("recurring_occurrences", ["series_id", "tenant_id", "recorded_definition_row_version"],
            "recurring_item_revisions", ["series_id", "tenant_id", "row_version"]))
    for table, source, parent, target in references:
        if not any(item["constrained_columns"] == source and item["referred_table"] == parent
            and item["referred_columns"] == target and item["options"].get("ondelete") == "RESTRICT"
            for item in inspector.get_foreign_keys(table)):
            raise RuntimeError("recurring definition evidence must retain its original ledger and series")


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    _assert_revision_shape(inspector)
    _assert_occurrence_basis(inspector)
    _assert_parent_guards(inspector)
    for table, trigger in (("recurring_item_revisions", "trg_recurring_item_revision_immutable"),
        ("recurring_occurrences", "trg_recurring_occurrence_definition_immutable")):
        triggers = set(bind.scalars(sa.text("SELECT tgname FROM pg_trigger WHERE tgrelid = CAST(:table AS regclass) "
            "AND NOT tgisinternal AND tgenabled = 'O'"), {"table": table}))
        if trigger not in triggers:
            raise RuntimeError("recurring definition immutability guard is missing")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with recurring history")
