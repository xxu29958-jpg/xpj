"""Preserve each staged CSV row's money context through later application."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0002"
down_revision = "20260908_0001"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the CSV currency migration edge")


def upgrade():
    bind = op.get_bind()
    op.add_column("csv_import_rows", sa.Column("home_currency_code", sa.String(3), nullable=True))
    # Do not issue even a zero-row UPDATE against an unadopted writer fence.
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")):
        bind.execute(sa.text(
            "SELECT set_config('xpj.currency_writer', currency_contract_version::text || ':' || binding_revision::text, true) "
            "FROM installation_currency_bindings WHERE singleton_id = 1"
        ))
        bind.execute(sa.text("""
            UPDATE csv_import_rows AS import_row SET home_currency_code = COALESCE(
                (SELECT expense.home_currency_code FROM expenses AS expense
                 WHERE expense.id = import_row.expense_id AND expense.tenant_id = import_row.tenant_id),
                binding.home_currency_code)
            FROM installation_currency_bindings AS binding WHERE binding.singleton_id = 1
        """))
    op.create_check_constraint("ck_csv_import_rows_home_currency", "csv_import_rows",
                              "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')")
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_csv_row_currency_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'CSV row requires its captured currency' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.home_currency_code IS NOT NULL
               AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
                RAISE EXCEPTION 'CSV row currency is immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_csv_row_currency BEFORE INSERT OR UPDATE ON csv_import_rows
        FOR EACH ROW EXECUTE FUNCTION ticketbox_csv_row_currency_guard();
    """)
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM csv_import_rows WHERE home_currency_code IS NOT NULL)")):
        raise RuntimeError("cannot erase captured CSV row currencies")
    op.execute("DROP TRIGGER IF EXISTS trg_csv_row_currency ON csv_import_rows")
    op.execute("DROP FUNCTION IF EXISTS ticketbox_csv_row_currency_guard()")
    op.drop_constraint("ck_csv_import_rows_home_currency", "csv_import_rows", type_="check")
    op.drop_column("csv_import_rows", "home_currency_code")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    column = next((col for col in inspector.get_columns("csv_import_rows") if col["name"] == "home_currency_code"), None)
    if column is None or not isinstance(column["type"], sa.String) or column["type"].length != 3 or column["default"] is not None:
        raise RuntimeError("CSV row currency context is missing or implicitly defaulted")
    if not bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'csv_import_rows'::regclass "
        "AND tgname = 'trg_csv_row_currency' AND NOT tgisinternal AND tgenabled = 'O')"
    )):
        raise RuntimeError("CSV row currency guard is missing")
    if bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")) and bind.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM csv_import_rows WHERE home_currency_code IS NULL)"
    )):
        raise RuntimeError("confirmed legacy CSV rows are missing their currency context")
