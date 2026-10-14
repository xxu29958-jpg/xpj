"""Expand recordable currencies without rescaling or changing existing money facts."""

import sqlalchemy as sa
from alembic import op

revision = "20261014_0001"
down_revision = "20261012_0001"
branch_labels = None
depends_on = None

# Frozen snapshot: later catalog changes require a new migration.
_OLD_CODES = "'CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW'"
_CODES = "'AED', 'AFN', 'ALL', 'AMD', 'AOA', 'ARS', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BYN', 'BZD', 'CAD', 'CDF', 'CHF', 'CLP', 'CNY', 'COP', 'CRC', 'CUP', 'CVE', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'EGP', 'ERN', 'ETB', 'EUR', 'FJD', 'FKP', 'GBP', 'GEL', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HTG', 'HUF', 'IDR', 'ILS', 'INR', 'IQD', 'IRR', 'ISK', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KPW', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'LYD', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRU', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SHP', 'SLE', 'SOS', 'SRD', 'SSP', 'STN', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TND', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'USD', 'UYU', 'UZS', 'VES', 'VND', 'VUV', 'WST', 'XAF', 'XCD', 'XCG', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMW', 'ZWG'"
_OLD_BINDING = "(\n    state = 'ACTIVE'\n    AND home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')\n    AND (\n        (home_currency_code IN ('JPY', 'KRW') AND minor_unit_exponent = 0)\n        OR\n        (home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'HKD') AND minor_unit_exponent = 2)\n    )\n    AND rounding_mode = 'ROUND_HALF_UP'\n    AND binding_revision >= 1\n    AND provenance IS NOT NULL\n    AND evidence_sha256 ~ '^[0-9a-f]{64}$'\n    AND activated_at IS NOT NULL\n)\nOR\n(\n    state IN ('EMPTY', 'ADOPTION_REQUIRED')\n    AND home_currency_code IS NULL\n    AND minor_unit_exponent IS NULL\n    AND rounding_mode IS NULL\n    AND binding_revision = 0\n    AND provenance IS NULL\n    AND evidence_sha256 IS NULL\n    AND activated_at IS NULL\n)"
_BINDING = "(\n    state = 'ACTIVE'\n    AND home_currency_code IN ('AED', 'AFN', 'ALL', 'AMD', 'AOA', 'ARS', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BHD', 'BIF', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BYN', 'BZD', 'CAD', 'CDF', 'CHF', 'CLP', 'CNY', 'COP', 'CRC', 'CUP', 'CVE', 'CZK', 'DJF', 'DKK', 'DOP', 'DZD', 'EGP', 'ERN', 'ETB', 'EUR', 'FJD', 'FKP', 'GBP', 'GEL', 'GHS', 'GIP', 'GMD', 'GNF', 'GTQ', 'GYD', 'HKD', 'HNL', 'HTG', 'HUF', 'IDR', 'ILS', 'INR', 'IQD', 'IRR', 'ISK', 'JMD', 'JOD', 'JPY', 'KES', 'KGS', 'KHR', 'KMF', 'KPW', 'KRW', 'KWD', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'LYD', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRU', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'OMR', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'PYG', 'QAR', 'RON', 'RSD', 'RUB', 'RWF', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SHP', 'SLE', 'SOS', 'SRD', 'SSP', 'STN', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TND', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'UGX', 'USD', 'UYU', 'UZS', 'VES', 'VND', 'VUV', 'WST', 'XAF', 'XCD', 'XCG', 'XOF', 'XPF', 'YER', 'ZAR', 'ZMW', 'ZWG')\n    AND (\n        (home_currency_code IN ('BIF', 'CLP', 'DJF', 'GNF', 'ISK', 'JPY', 'KMF', 'KRW', 'PYG', 'RWF', 'UGX', 'VND', 'VUV', 'XAF', 'XOF', 'XPF') AND minor_unit_exponent = 0) OR (home_currency_code IN ('AED', 'AFN', 'ALL', 'AMD', 'AOA', 'ARS', 'AUD', 'AWG', 'AZN', 'BAM', 'BBD', 'BDT', 'BMD', 'BND', 'BOB', 'BRL', 'BSD', 'BTN', 'BWP', 'BYN', 'BZD', 'CAD', 'CDF', 'CHF', 'CNY', 'COP', 'CRC', 'CUP', 'CVE', 'CZK', 'DKK', 'DOP', 'DZD', 'EGP', 'ERN', 'ETB', 'EUR', 'FJD', 'FKP', 'GBP', 'GEL', 'GHS', 'GIP', 'GMD', 'GTQ', 'GYD', 'HKD', 'HNL', 'HTG', 'HUF', 'IDR', 'ILS', 'INR', 'IRR', 'JMD', 'KES', 'KGS', 'KHR', 'KPW', 'KYD', 'KZT', 'LAK', 'LBP', 'LKR', 'LRD', 'LSL', 'MAD', 'MDL', 'MGA', 'MKD', 'MMK', 'MNT', 'MOP', 'MRU', 'MUR', 'MVR', 'MWK', 'MXN', 'MYR', 'MZN', 'NAD', 'NGN', 'NIO', 'NOK', 'NPR', 'NZD', 'PAB', 'PEN', 'PGK', 'PHP', 'PKR', 'PLN', 'QAR', 'RON', 'RSD', 'RUB', 'SAR', 'SBD', 'SCR', 'SDG', 'SEK', 'SGD', 'SHP', 'SLE', 'SOS', 'SRD', 'SSP', 'STN', 'SYP', 'SZL', 'THB', 'TJS', 'TMT', 'TOP', 'TRY', 'TTD', 'TWD', 'TZS', 'UAH', 'USD', 'UYU', 'UZS', 'VES', 'WST', 'XCD', 'XCG', 'YER', 'ZAR', 'ZMW', 'ZWG') AND minor_unit_exponent = 2) OR (home_currency_code IN ('BHD', 'IQD', 'JOD', 'KWD', 'LYD', 'OMR', 'TND') AND minor_unit_exponent = 3)\n    )\n    AND rounding_mode = 'ROUND_HALF_UP'\n    AND binding_revision >= 1\n    AND provenance IS NOT NULL\n    AND evidence_sha256 ~ '^[0-9a-f]{64}$'\n    AND activated_at IS NOT NULL\n)\nOR\n(\n    state IN ('EMPTY', 'ADOPTION_REQUIRED')\n    AND home_currency_code IS NULL\n    AND minor_unit_exponent IS NULL\n    AND rounding_mode IS NULL\n    AND binding_revision = 0\n    AND provenance IS NULL\n    AND evidence_sha256 IS NULL\n    AND activated_at IS NULL\n)"
_CHECKS = (
    ("budgets", "ck_budget_currency"), ("goals", "ck_goal_currency"),
    ("category_rules", "ck_category_rule_currency"), ("monthly_income_plans", "ck_income_plan_currency"),
    ("income_plan_revisions", "ck_income_revision_currency"), ("csv_import_rows", "ck_csv_import_rows_home_currency"),
    ("monthly_arrangements", "ck_monthly_arrangement_currency"),
    ("monthly_arrangement_revisions", "ck_monthly_arrangement_revision_currency"),
    ("recurring_items", "ck_recurring_currency"), ("exchange_rates", "ck_exchange_rates_home_currency"),
)


def _replace_checks(codes, binding):
    for table, name in _CHECKS:
        op.drop_constraint(name, table, type_="check")
        expression = f"home_currency_code IN ({codes})"
        if table == "exchange_rates":
            expression += " AND home_currency_code <> currency_code"
        op.create_check_constraint(name, table, expression)
    op.drop_constraint("ck_installation_currency_binding_shape", "installation_currency_bindings", type_="check")
    op.create_check_constraint("ck_installation_currency_binding_shape", "installation_currency_bindings", binding)


def _set_revision(expected, target):
    changed = op.get_bind().execute(sa.text("UPDATE dataset_authority SET schema_revision=:target "
        "WHERE singleton_id=1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the currency catalog edge")


def upgrade():
    _replace_checks(_CODES, _BINDING)
    _set_revision(down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    # Include original-currency legs and reference records, not only default/home fields.
    columns = bind.execute(sa.text("SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND data_type IN ('character varying', 'text') "
        "AND column_name IN ('currency_code','home_currency_code','original_currency_code', 'provider_base_currency')"))
    quote = bind.dialect.identifier_preparer.quote
    new_codes = ", ".join(code for code in _CODES.split(", ") if code not in _OLD_CODES.split(", "))
    for table, column in columns:
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {quote(table)} WHERE {quote(column)} IN ({new_codes}))")):
            raise RuntimeError("cannot remove currency support while expanded-currency records exist")
    _replace_checks(_OLD_CODES, _OLD_BINDING)
    _set_revision(revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    for table, name in (*_CHECKS, ("installation_currency_bindings", "ck_installation_currency_binding_shape")):
        check = next((item for item in inspector.get_check_constraints(table) if item["name"] == name), None)
        if check is None or any(f"'{code}'" not in check["sqltext"] for code in ("TWD", "VND", "KWD", "ZWG")):
            raise RuntimeError(f"currency catalog constraint is missing: {table}")
