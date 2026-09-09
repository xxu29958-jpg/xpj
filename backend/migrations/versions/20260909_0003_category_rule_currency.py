"""Amount-bearing category rules retain their threshold currency."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0003"
down_revision = "20260909_0002"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the rule currency migration edge")


def upgrade():
    bind = op.get_bind()
    op.add_column("category_rules", sa.Column("home_currency_code", sa.String(3), nullable=True))
    op.create_check_constraint("ck_category_rule_currency", "category_rules",
        "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_category_rule_currency_required()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF (NEW.amount_min_cents IS NOT NULL OR NEW.amount_max_cents IS NOT NULL)
               AND NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'monetary rule requires its captured currency' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.home_currency_code IS NOT NULL
               AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
                RAISE EXCEPTION 'rule currency cannot relabel saved thresholds' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_category_rule_currency_required BEFORE INSERT OR UPDATE ON category_rules
        FOR EACH ROW EXECUTE FUNCTION ticketbox_category_rule_currency_required();
    """)
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")):
        bind.execute(sa.text(
            "SELECT set_config('xpj.currency_writer', currency_contract_version::text || ':' || binding_revision::text, true) "
            "FROM installation_currency_bindings WHERE singleton_id = 1"
        ))
        bind.execute(sa.text("UPDATE category_rules SET home_currency_code = binding.home_currency_code "
            "FROM installation_currency_bindings AS binding WHERE binding.singleton_id = 1 "
            "AND (category_rules.amount_min_cents IS NOT NULL OR category_rules.amount_max_cents IS NOT NULL)"))
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM category_rules WHERE home_currency_code IS NOT NULL)")):
        raise RuntimeError("cannot erase recorded rule currencies")
    op.execute("DROP TRIGGER trg_category_rule_currency_required ON category_rules")
    op.execute("DROP FUNCTION ticketbox_category_rule_currency_required()")
    op.drop_constraint("ck_category_rule_currency", "category_rules", type_="check")
    op.drop_column("category_rules", "home_currency_code")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    column = next((col for col in inspector.get_columns("category_rules") if col["name"] == "home_currency_code"), None)
    if column is None or not isinstance(column["type"], sa.String) or column["type"].length != 3 or column["default"] is not None:
        raise RuntimeError("rule currency is missing or implicitly defaulted")
    if "ck_category_rule_currency" not in {check["name"] for check in inspector.get_check_constraints("category_rules")}:
        raise RuntimeError("rule currency constraint is missing")
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")) and bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM category_rules WHERE "
            "(amount_min_cents IS NOT NULL OR amount_max_cents IS NOT NULL) AND home_currency_code IS NULL)")
    ):
        raise RuntimeError("confirmed legacy rule is missing its recorded currency")
    if not bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'category_rules'::regclass "
        "AND tgname = 'trg_category_rule_currency_required' AND NOT tgisinternal AND tgenabled = 'O')")):
        raise RuntimeError("rule currency guard is missing")
