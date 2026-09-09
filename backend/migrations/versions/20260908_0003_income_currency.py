"""Attach recorded currency to income amounts without changing their history."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0003"
down_revision = "20260908_0002"
branch_labels = None
depends_on = None
_TABLES = {"monthly_income_plans": "ck_income_plan_currency", "income_plan_revisions": "ck_income_revision_currency"}


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the income currency migration edge")


def _install_currency_guards():
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_income_currency_required()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'income requires its captured currency' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE OR REPLACE FUNCTION ticketbox_income_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP = 'UPDATE' AND OLD.home_currency_code IS NULL
               AND NEW.home_currency_code IS NOT NULL
               AND (to_jsonb(NEW) - 'home_currency_code') IS NOT DISTINCT FROM (to_jsonb(OLD) - 'home_currency_code')
               AND EXISTS (
                   SELECT 1 FROM installation_currency_bindings
                   WHERE singleton_id = 1 AND state = 'ACTIVE' AND home_currency_code = NEW.home_currency_code
                     AND current_setting('xpj.currency_writer', true) = currency_contract_version::text || ':' || binding_revision::text
               ) THEN RETURN NEW;
            END IF;
            RAISE EXCEPTION 'income plan revisions are immutable' USING ERRCODE = '55000';
        END $$;
    """)
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER trg_income_currency_required BEFORE INSERT OR UPDATE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION ticketbox_income_currency_required()")
    op.execute("""
        CREATE TRIGGER trg_currency_writer_income_plan_revisions
        BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON income_plan_revisions
        FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_require_currency_writer();
    """)


def upgrade():
    bind = op.get_bind()
    for table, constraint in _TABLES.items():
        op.add_column(table, sa.Column("home_currency_code", sa.String(3), nullable=True))
        op.create_check_constraint(constraint, table, "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')")
    _install_currency_guards()
    # Unknown legacy history remains unknown until the audited Owner adoption.
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")):
        bind.execute(sa.text(
            "SELECT set_config('xpj.currency_writer', currency_contract_version::text || ':' || binding_revision::text, true) "
            "FROM installation_currency_bindings WHERE singleton_id = 1"
        ))
        for table in _TABLES:
            bind.execute(sa.text(f"UPDATE {table} SET home_currency_code = binding.home_currency_code "
                                 "FROM installation_currency_bindings AS binding WHERE binding.singleton_id = 1"))
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    for table in _TABLES:
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE home_currency_code IS NOT NULL)")):
            raise RuntimeError("cannot erase recorded income currencies")
    op.execute("DROP TRIGGER trg_currency_writer_income_plan_revisions ON income_plan_revisions")
    for table, constraint in _TABLES.items():
        op.execute(f"DROP TRIGGER trg_income_currency_required ON {table}")
        op.drop_constraint(constraint, table, type_="check")
        op.drop_column(table, "home_currency_code")
    op.execute("DROP FUNCTION ticketbox_income_currency_required()")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_income_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'income plan revisions are immutable' USING ERRCODE = '55000';
        END $$;
    """)
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    active = bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1"))
    for table, constraint in _TABLES.items():
        column = next((col for col in inspector.get_columns(table) if col["name"] == "home_currency_code"), None)
        if column is None or not isinstance(column["type"], sa.String) or column["type"].length != 3 or column["default"] is not None:
            raise RuntimeError("income currency is missing or implicitly defaulted")
        if constraint not in {check["name"] for check in inspector.get_check_constraints(table)}:
            raise RuntimeError("income currency constraint is missing")
        if active and bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE home_currency_code IS NULL)")):
            raise RuntimeError("confirmed legacy income is missing its recorded currency")
        triggers = set(bind.scalars(sa.text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:table) AND NOT tgisinternal AND tgenabled = 'O'"
        ), {"table": table}))
        required = {"trg_income_currency_required"}
        if table == "income_plan_revisions":
            required |= {"trg_income_plan_revision_immutable", "trg_currency_writer_income_plan_revisions"}
        if not required <= triggers:
            raise RuntimeError("income currency or immutable revision guard is missing")
