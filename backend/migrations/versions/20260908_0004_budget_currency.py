"""Budgets retain their currency; category limits inherit the existing parent."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0004"
down_revision = "20260908_0003"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the budget currency migration edge")


def upgrade():
    bind = op.get_bind()
    op.add_column("budgets", sa.Column("home_currency_code", sa.String(3), nullable=True))
    op.create_check_constraint("ck_budget_currency", "budgets", "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_budget_currency_required()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'budget requires its captured currency' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.home_currency_code IS NOT NULL
               AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
                RAISE EXCEPTION 'budget currency cannot relabel saved amounts' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_budget_currency_required BEFORE INSERT OR UPDATE ON budgets
        FOR EACH ROW EXECUTE FUNCTION ticketbox_budget_currency_required();
    """)
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")):
        bind.execute(sa.text(
            "SELECT set_config('xpj.currency_writer', currency_contract_version::text || ':' || binding_revision::text, true) "
            "FROM installation_currency_bindings WHERE singleton_id = 1"
        ))
        bind.execute(sa.text("UPDATE budgets SET home_currency_code = binding.home_currency_code "
            "FROM installation_currency_bindings AS binding WHERE binding.singleton_id = 1"))
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM budgets WHERE home_currency_code IS NOT NULL)")):
        raise RuntimeError("cannot erase recorded budget currencies")
    op.execute("DROP TRIGGER trg_budget_currency_required ON budgets")
    op.execute("DROP FUNCTION ticketbox_budget_currency_required()")
    op.drop_constraint("ck_budget_currency", "budgets", type_="check")
    op.drop_column("budgets", "home_currency_code")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    column = next((col for col in inspector.get_columns("budgets") if col["name"] == "home_currency_code"), None)
    if column is None or not isinstance(column["type"], sa.String) or column["type"].length != 3 or column["default"] is not None:
        raise RuntimeError("budget currency is missing or implicitly defaulted")
    if "ck_budget_currency" not in {check["name"] for check in inspector.get_check_constraints("budgets")}:
        raise RuntimeError("budget currency constraint is missing")
    if "fk_budget_categories_budget_month" not in {fk["name"] for fk in inspector.get_foreign_keys("budget_categories")}:
        raise RuntimeError("category budget has no currency-owning parent")
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")) and bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM budgets WHERE home_currency_code IS NULL)")
    ):
        raise RuntimeError("confirmed legacy budget is missing its recorded currency")
    if not bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'budgets'::regclass "
        "AND tgname = 'trg_budget_currency_required' AND NOT tgisinternal AND tgenabled = 'O')")):
        raise RuntimeError("budget currency guard is missing")
