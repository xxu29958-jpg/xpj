"""Preserve the target currency of each manual exchange rate."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0001"
down_revision = "20260907_0001"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    updated = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority is outside the manual rate currency migration edge")


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "home_currency_code" not in {item["name"] for item in inspector.get_columns("exchange_rates")}:
        op.add_column("exchange_rates", sa.Column("home_currency_code", sa.String(3), nullable=True))
    # Only a persisted ACTIVE choice proves these legacy rates' target. An
    # unadopted installation keeps NULL until its Owner confirms in one transaction.
    bind.execute(sa.text(
        "SELECT set_config('xpj.currency_writer', currency_contract_version::text || ':' || binding_revision::text, true) "
        "FROM installation_currency_bindings WHERE singleton_id = 1 AND state = 'ACTIVE'"
    ))
    bind.execute(sa.text(
        "UPDATE exchange_rates AS rate SET home_currency_code = binding.home_currency_code "
        "FROM installation_currency_bindings AS binding "
        "WHERE binding.singleton_id = 1 AND binding.state = 'ACTIVE' AND rate.home_currency_code IS NULL"
    ))
    uniques = {item["name"] for item in inspector.get_unique_constraints("exchange_rates")}
    if "uq_exchange_rates_tenant_currency_date" in uniques:
        op.drop_constraint("uq_exchange_rates_tenant_currency_date", "exchange_rates", type_="unique")
    if "uq_exchange_rates_tenant_pair_date" not in uniques:
        op.create_unique_constraint("uq_exchange_rates_tenant_pair_date", "exchange_rates", [
            "tenant_id", "home_currency_code", "currency_code", "rate_date",
        ])
    if "ck_exchange_rates_home_currency" not in {item["name"] for item in inspector.get_check_constraints("exchange_rates")}:
        op.create_check_constraint("ck_exchange_rates_home_currency", "exchange_rates",
            "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW') AND home_currency_code <> currency_code")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_manual_rate_currency_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'manual exchange rate requires target currency' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (OLD.home_currency_code IS NOT NULL AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code)
                OR NEW.currency_code IS DISTINCT FROM OLD.currency_code
                OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.rate_date IS DISTINCT FROM OLD.rate_date
            ) THEN
                RAISE EXCEPTION 'manual exchange rate currency pair is immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER IF EXISTS trg_manual_rate_currency ON exchange_rates;
        CREATE TRIGGER trg_manual_rate_currency BEFORE INSERT OR UPDATE ON exchange_rates
        FOR EACH ROW EXECUTE FUNCTION ticketbox_manual_rate_currency_guard();
    """)
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM exchange_rates WHERE home_currency_code IS NOT NULL)")):
        raise RuntimeError("cannot erase persisted manual rate currencies")
    op.execute("DROP TRIGGER IF EXISTS trg_manual_rate_currency ON exchange_rates")
    op.execute("DROP FUNCTION IF EXISTS ticketbox_manual_rate_currency_guard()")
    op.drop_constraint("ck_exchange_rates_home_currency", "exchange_rates", type_="check")
    op.drop_constraint("uq_exchange_rates_tenant_pair_date", "exchange_rates", type_="unique")
    op.create_unique_constraint("uq_exchange_rates_tenant_currency_date", "exchange_rates", ["tenant_id", "currency_code", "rate_date"])
    op.drop_column("exchange_rates", "home_currency_code")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    column = next((item for item in inspector.get_columns("exchange_rates") if item["name"] == "home_currency_code"), None)
    if column is None or not isinstance(column["type"], sa.String) or column["type"].length != 3:
        raise RuntimeError("manual rate target currency column is missing")
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("exchange_rates")}
    if ("tenant_id", "home_currency_code", "currency_code", "rate_date") not in uniques:
        raise RuntimeError("manual rate currency pair uniqueness is missing")
    if ("tenant_id", "currency_code", "rate_date") in uniques:
        raise RuntimeError("legacy manual rate uniqueness still merges different targets")
    if not bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'exchange_rates'::regclass "
        "AND tgname = 'trg_manual_rate_currency' AND NOT tgisinternal AND tgenabled = 'O')"
    )):
        raise RuntimeError("manual rate currency guard is missing")
    if bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM exchange_rates, installation_currency_bindings "
        "WHERE state = 'ACTIVE' AND exchange_rates.home_currency_code IS NULL)"
    )):
        raise RuntimeError("confirmed installation has manual rates without a currency")
    live_revision = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected_revision = revision if live_revision == down_revision else live_revision
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected_revision:
        raise RuntimeError("dataset authority is not aligned with manual rate currencies")
