"""Fixed expenses capture their money currency without changing saved amounts."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_0001"
down_revision = "20260908_0004"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the recurring currency migration edge")


def upgrade():
    bind = op.get_bind()
    op.add_column("recurring_items", sa.Column("home_currency_code", sa.String(3), nullable=True))
    op.create_check_constraint("ck_recurring_currency", "recurring_items", "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_recurring_currency_required()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'recurring requires its captured currency' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.home_currency_code IS NOT NULL
               AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
                RAISE EXCEPTION 'recurring currency cannot relabel saved amounts' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_recurring_currency_required BEFORE INSERT OR UPDATE ON recurring_items
        FOR EACH ROW EXECUTE FUNCTION ticketbox_recurring_currency_required();
    """)
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")):
        bind.execute(sa.text(
            "SELECT set_config('xpj.currency_writer', currency_contract_version::text || ':' || binding_revision::text, true) "
            "FROM installation_currency_bindings WHERE singleton_id = 1"
        ))
        bind.execute(sa.text("UPDATE recurring_items SET home_currency_code = binding.home_currency_code "
            "FROM installation_currency_bindings AS binding WHERE binding.singleton_id = 1"))
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM recurring_items WHERE home_currency_code IS NOT NULL)")):
        raise RuntimeError("cannot erase recorded recurring currencies")
    op.execute("DROP TRIGGER trg_recurring_currency_required ON recurring_items")
    op.execute("DROP FUNCTION ticketbox_recurring_currency_required()")
    op.drop_constraint("ck_recurring_currency", "recurring_items", type_="check")
    op.drop_column("recurring_items", "home_currency_code")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    column = next((col for col in inspector.get_columns("recurring_items") if col["name"] == "home_currency_code"), None)
    if column is None or not isinstance(column["type"], sa.String) or column["type"].length != 3 or column["default"] is not None:
        raise RuntimeError("recurring currency is missing or implicitly defaulted")
    if "ck_recurring_currency" not in {check["name"] for check in inspector.get_check_constraints("recurring_items")}:
        raise RuntimeError("recurring currency constraint is missing")
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")) and bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM recurring_items WHERE home_currency_code IS NULL)")
    ):
        raise RuntimeError("confirmed legacy recurring item is missing its recorded currency")
    if not bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'recurring_items'::regclass "
        "AND tgname = 'trg_recurring_currency_required' AND NOT tgisinternal AND tgenabled = 'O')")):
        raise RuntimeError("recurring currency guard is missing")
