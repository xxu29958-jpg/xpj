"""Explicit cash-purpose allocations beside existing monthly plans."""
import sqlalchemy as sa
from alembic import op

revision = "20261019_0001"
down_revision = "20261018_0004"
branch_labels = None
depends_on = None


def _set_revision(expected, target):
    result = op.get_bind().execute(sa.text("UPDATE dataset_authority SET schema_revision = :target WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the envelope allocation migration edge")


def upgrade():
    op.execute("\nCREATE TABLE envelope_books (\n\ttenant_id VARCHAR(64) NOT NULL, \n\thome_currency_code VARCHAR(3) NOT NULL, \n\trow_version INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (tenant_id), \n\tCONSTRAINT ck_envelope_book_version CHECK (row_version > 0), \n\tCONSTRAINT ck_envelope_book_currency CHECK (home_currency_code IN ('AED', 'AFN', 'ALL', 'AMD', 'AOA', 'ARS', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BYN', 'BZD', 'CAD', 'CDF', 'CHF', 'CLP', 'CNY', 'COP', 'CRC', 'CUP', 'CVE', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'EGP', 'ERN', 'ETB', 'EUR', 'FJD', 'FKP', 'GBP', 'GEL', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HTG', 'HUF', 'IDR', 'ILS', 'INR', 'IQD', 'IRR', 'ISK', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KPW', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'LYD', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRU', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SHP', 'SLE', 'SOS', 'SRD', 'SSP', 'STN', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TND', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'USD', 'UYU', 'UZS', 'VES', 'VND', 'VUV', 'WST', 'XAF', 'XCD', 'XCG', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMW', 'ZWG')), \n\tFOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)\n)\n\n")
    op.execute('\nCREATE TABLE envelope_sources (\n\taccount_id INTEGER NOT NULL, \n\ttenant_id VARCHAR(64) NOT NULL, \n\tPRIMARY KEY (account_id), \n\tFOREIGN KEY(account_id) REFERENCES financial_accounts (id), \n\tFOREIGN KEY(tenant_id) REFERENCES envelope_books (tenant_id)\n)\n\n')
    op.execute('CREATE INDEX ix_envelope_sources_tenant_id ON envelope_sources (tenant_id)')
    op.execute("\nCREATE TABLE envelope_allocations (\n\ttenant_id VARCHAR(64) NOT NULL, \n\tmonth VARCHAR(7) NOT NULL, \n\tpurpose VARCHAR(80) NOT NULL, \n\tallocated_minor BIGINT NOT NULL, \n\tPRIMARY KEY (tenant_id, month, purpose), \n\tCONSTRAINT ck_envelope_allocations_allocated_minor_money_bounds CHECK (allocated_minor BETWEEN 0 AND 9000000000000), \n\tCONSTRAINT ck_envelope_allocation_month CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'), \n\tCONSTRAINT ck_envelope_allocation_purpose CHECK (purpose IN ('spending','savings','buffer') OR purpose LIKE 'category:%%'), \n\tFOREIGN KEY(tenant_id) REFERENCES envelope_books (tenant_id)\n)\n\n")
    op.execute('\nCREATE TABLE envelope_revisions (\n\ttenant_id VARCHAR(64) NOT NULL, \n\trow_version INTEGER NOT NULL, \n\tactor_account_id INTEGER NOT NULL, \n\tmonth VARCHAR(7) NOT NULL, \n\treason VARCHAR(255) NOT NULL, \n\tallocation_snapshot JSON NOT NULL, \n\trecorded_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (tenant_id, row_version), \n\tCONSTRAINT ck_envelope_revision_version CHECK (row_version > 0), \n\tFOREIGN KEY(tenant_id) REFERENCES envelope_books (tenant_id), \n\tFOREIGN KEY(actor_account_id) REFERENCES accounts (id)\n)\n\n')
    op.execute("\nCREATE OR REPLACE FUNCTION ticketbox_envelope_currency_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n    IF NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN\n        RAISE EXCEPTION 'envelope currency cannot relabel assigned amounts' USING ERRCODE = '23514';\n    END IF;\n    RETURN NEW;\nEND $$;\nCREATE TRIGGER trg_envelope_currency_guard BEFORE UPDATE ON envelope_books\n    FOR EACH ROW EXECUTE FUNCTION ticketbox_envelope_currency_guard();\nCREATE OR REPLACE FUNCTION ticketbox_envelope_revision_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n    RAISE EXCEPTION 'envelope revisions are immutable' USING ERRCODE = '55000';\nEND $$;\nCREATE TRIGGER trg_envelope_revision_immutable BEFORE UPDATE OR DELETE ON envelope_revisions\n    FOR EACH ROW EXECUTE FUNCTION ticketbox_envelope_revision_immutable();\nCREATE TRIGGER trg_envelope_revision_no_truncate BEFORE TRUNCATE ON envelope_revisions\n    FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_envelope_revision_immutable();\n")
    _set_revision(down_revision, revision)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM envelope_books)")):
        raise RuntimeError("Funded purposes and their history must remain readable; downgrade refused.")
    for table in ("envelope_revisions", "envelope_allocations", "envelope_sources", "envelope_books"):
        op.drop_table(table)
    op.execute("DROP FUNCTION ticketbox_envelope_currency_guard()")
    op.execute("DROP FUNCTION ticketbox_envelope_revision_immutable()")
    _set_revision(revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    if not {"envelope_books", "envelope_sources", "envelope_allocations", "envelope_revisions"} <= set(inspector.get_table_names()):
        raise RuntimeError("cash-purpose allocation tables are missing")
    names = set(bind.execute(sa.text("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg_envelope_%'")).scalars())
    if names != {"trg_envelope_currency_guard", "trg_envelope_revision_immutable", "trg_envelope_revision_no_truncate"}:
        raise RuntimeError("cash-purpose currency/history guards are missing")
