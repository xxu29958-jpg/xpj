"""Capture monthly set-aside intentions without deriving them from old budgets.

Revision ID: 20260927_0001
Revises: 20260926_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0001"
down_revision = "20260926_0001"
branch_labels = None
depends_on = None
_TABLES = ("monthly_arrangements", "monthly_arrangement_revisions")
_MAX = 9_000_000_000_000
_CURRENCY = "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')"


def _money_columns():
    return [sa.Column("home_currency_code", sa.String(3), nullable=False),
        sa.Column("savings_target_cents", sa.BigInteger(), nullable=False),
        sa.Column("reserved_buffer_cents", sa.BigInteger(), nullable=False)]


def _money_checks(prefix):
    return [sa.CheckConstraint(f"{column} BETWEEN 0 AND {_MAX}", name=f"ck_{prefix}_{column}_money_bounds")
        for column in ("savings_target_cents", "reserved_buffer_cents")]


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text("UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the monthly arrangement edge")


def upgrade():
    op.create_table("monthly_arrangements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("month", sa.String(7), nullable=False), *_money_columns(),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["ledgers.ledger_id"], name="fk_monthly_arrangement_ledger"),
        sa.UniqueConstraint("tenant_id", "month", name="uq_monthly_arrangement_tenant_month"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_monthly_arrangement_id_tenant"),
        sa.CheckConstraint("month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_monthly_arrangement_month"),
        sa.CheckConstraint("row_version >= 1", name="ck_monthly_arrangement_version"),
        sa.CheckConstraint(_CURRENCY, name="ck_monthly_arrangement_currency"), *_money_checks("monthly_arrangement"))
    op.create_table("monthly_arrangement_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("arrangement_id", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False), *_money_columns(),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["arrangement_id", "tenant_id"], ["monthly_arrangements.id", "monthly_arrangements.tenant_id"],
            name="fk_monthly_arrangement_revision_parent", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], name="fk_monthly_arrangement_revision_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "arrangement_id", "row_version", name="uq_monthly_arrangement_revision_version"),
        sa.CheckConstraint("row_version >= 1", name="ck_monthly_arrangement_revision_version"),
        sa.CheckConstraint(_CURRENCY, name="ck_monthly_arrangement_revision_currency"), *_money_checks("monthly_arrangement_rev"))
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_monthly_arrangement_currency_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
                RAISE EXCEPTION 'monthly arrangement currency cannot relabel saved amounts' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_monthly_arrangement_currency_guard BEFORE UPDATE ON monthly_arrangements
        FOR EACH ROW EXECUTE FUNCTION ticketbox_monthly_arrangement_currency_guard();
        CREATE OR REPLACE FUNCTION ticketbox_monthly_arrangement_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'monthly arrangement revisions are immutable' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER trg_monthly_arrangement_revision_immutable BEFORE UPDATE OR DELETE ON monthly_arrangement_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_monthly_arrangement_revision_immutable();
        CREATE TRIGGER trg_monthly_arrangement_revision_no_truncate BEFORE TRUNCATE ON monthly_arrangement_revisions
        FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_monthly_arrangement_revision_immutable();
    """)
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER trg_currency_writer_{table} BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_require_currency_writer()")
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM monthly_arrangements) OR "
        "EXISTS (SELECT 1 FROM monthly_arrangement_revisions)")):
        raise RuntimeError("cannot erase saved monthly arrangements")
    op.drop_table("monthly_arrangement_revisions")
    op.drop_table("monthly_arrangements")
    op.execute("DROP FUNCTION ticketbox_monthly_arrangement_revision_immutable()")
    op.execute("DROP FUNCTION ticketbox_monthly_arrangement_currency_guard()")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    for table, prefix in zip(_TABLES, ("monthly_arrangement", "monthly_arrangement_rev"), strict=True):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        for column in ("tenant_id", "home_currency_code", "savings_target_cents", "reserved_buffer_cents", "row_version"):
            if column not in columns or columns[column]["nullable"]:
                raise RuntimeError("monthly arrangement is missing captured facts")
        for column in ("savings_target_cents", "reserved_buffer_cents"):
            if not isinstance(columns[column]["type"], sa.BigInteger):
                raise RuntimeError("monthly arrangement money requires bigint")
        checks = {item["name"] for item in inspector.get_check_constraints(table)}
        required = {f"ck_{prefix}_{column}_money_bounds" for column in ("savings_target_cents", "reserved_buffer_cents")}
        if not required <= checks:
            raise RuntimeError("monthly arrangement money bounds are missing")
        triggers = set(bind.scalars(sa.text("SELECT tgname FROM pg_trigger WHERE tgrelid = CAST(:table AS regclass) "
            "AND NOT tgisinternal AND tgenabled = 'O'"), {"table": table}))
        required_triggers = {f"trg_currency_writer_{table}"}
        required_triggers |= ({"trg_monthly_arrangement_currency_guard"} if table == "monthly_arrangements"
            else {"trg_monthly_arrangement_revision_immutable", "trg_monthly_arrangement_revision_no_truncate"})
        if not required_triggers <= triggers:
            raise RuntimeError("monthly arrangement guards are missing")
    for table, key in (("monthly_arrangements", ("tenant_id", "month")),
        ("monthly_arrangement_revisions", ("tenant_id", "arrangement_id", "row_version"))):
        if key not in {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table)}:
            raise RuntimeError("monthly arrangement identity is missing")
    foreign_keys = inspector.get_foreign_keys("monthly_arrangement_revisions")
    if not any(item["constrained_columns"] == ["arrangement_id", "tenant_id"]
        and item["referred_table"] == "monthly_arrangements" and item["referred_columns"] == ["id", "tenant_id"]
        and item["options"].get("ondelete") == "RESTRICT" for item in foreign_keys):
        raise RuntimeError("monthly arrangement history must retain its ledger and parent")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with monthly arrangements")
