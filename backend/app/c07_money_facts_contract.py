"""Frozen source-existing semantic manifest for the C07 money-fact digest."""

from __future__ import annotations

from app.money_contract import MONEY_COLUMNS_V1

MONEY_FACTS_SCHEMA = "ticketbox-c07-semantic-money-facts-v1"
INSTALLATION_HOME_CURRENCY_KEY = "installation_home_currency"
MONEY_FACT_CONTEXT_COLUMNS_V1 = (
    (
        "bill_split_invitations",
        (
            "public_id",
            "sender_expense_id",
            "sender_account_id",
            "sender_ledger_id",
            "sender_member_id",
            "receiver_account_id",
            "receiver_ledger_id",
            "receiver_member_id",
            "received_expense_id",
            "home_currency_code",
            "original_currency_code",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
            "status",
        ),
    ),
    (
        "budget_categories",
        ("public_id", "tenant_id", "month", "category"),
    ),
    ("budgets", ("public_id", "tenant_id", "month", "archived_at")),
    (
        "category_rules",
        (
            "tenant_id",
            "keyword",
            "category",
            "enabled",
            "source_contains",
            "tag_contains",
            "deleted_at",
        ),
    ),
    (
        "csv_import_rows",
        (
            "tenant_id",
            "batch_id",
            "line_number",
            "status",
            "expense_id",
            "original_currency_code",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
        ),
    ),
    (
        "debt_adjustments",
        ("public_id", "debt_id", "actor_account_id"),
    ),
    (
        "debt_forgivenesses",
        ("public_id", "debt_id", "actor_account_id"),
    ),
    (
        "debts",
        (
            "public_id",
            "tenant_id",
            "owner_account_id",
            "direction",
            "counterparty_type",
            "counterparty_account_id",
            "home_currency_code",
            "original_currency_code",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
            "status",
            "debt_kind",
            "source_type",
            "source_id",
        ),
    ),
    (
        "expense_items",
        (
            "public_id",
            "tenant_id",
            "expense_id",
            "position",
            "kind",
            "is_ocr_draft",
        ),
    ),
    (
        "expense_splits",
        ("public_id", "tenant_id", "expense_id", "member_id", "position"),
    ),
    (
        "expenses",
        (
            "public_id",
            "tenant_id",
            "home_currency_code",
            "original_currency_code",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
            "fx_status",
            "status",
            "duplicate_of_id",
            "split_origin_invitation_id",
        ),
    ),
    (
        "goals",
        (
            "public_id",
            "tenant_id",
            "goal_type",
            "period",
            "month",
            "category",
            "status",
            "archived_at",
        ),
    ),
    (
        "member_repayment_proposals",
        (
            "public_id",
            "debt_id",
            "debtor_account_id",
            "creditor_account_id",
            "home_currency_code",
            "original_currency_code",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
            "status",
            "committed_repayment_id",
        ),
    ),
    (
        "monthly_income_plans",
        (
            "public_id",
            "tenant_id",
            "source_type",
            "frequency",
            "income_month",
            "status",
            "archived_at",
        ),
    ),
    ("ocr_facts", ("public_id", "tenant_id", "expense_id")),
    (
        "recurring_items",
        ("public_id", "tenant_id", "frequency", "status", "archived_at"),
    ),
    (
        "repayment_drafts",
        (
            "public_id",
            "tenant_id",
            "created_by_account_id",
            "home_currency_code",
            "status",
            "committed_debt_public_id",
            "committed_repayment_public_id",
        ),
    ),
    (
        "repayments",
        (
            "public_id",
            "debt_id",
            "original_currency_code",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
            "proposal_id",
        ),
    ),
)

MONEY_FACT_TABLES = tuple(
    sorted({contract.table for contract in MONEY_COLUMNS_V1})
)
assert tuple(table for table, _columns in MONEY_FACT_CONTEXT_COLUMNS_V1) == (
    MONEY_FACT_TABLES
)

__all__ = [
    "INSTALLATION_HOME_CURRENCY_KEY",
    "MONEY_FACT_CONTEXT_COLUMNS_V1",
    "MONEY_FACT_TABLES",
    "MONEY_FACTS_SCHEMA",
]
