"""Runtime constants for the persisted installation currency authority."""

from __future__ import annotations

CURRENCY_CONTRACT_VERSION = 1
MINIMUM_WRITABLE_CURRENCY_CONTRACT = 1
INITIAL_BINDING_REVISION = 1
CURRENCY_ROUNDING_MODE = "ROUND_HALF_UP"
CURRENCY_WRITER_GUC = "xpj.currency_writer"

CURRENCY_BINDING_EMPTY = "EMPTY"
CURRENCY_BINDING_ADOPTION_REQUIRED = "ADOPTION_REQUIRED"
CURRENCY_BINDING_ACTIVE = "ACTIVE"

CURRENCY_EVIDENCE_TABLES = (
    "bill_split_invitations",
    "budget_categories",
    "budgets",
    "category_rules",
    "csv_import_rows",
    "debt_adjustments",
    "debt_forgivenesses",
    "debts",
    "expense_items",
    "expense_splits",
    "expenses",
    "exchange_rates",
    "goals",
    "member_repayment_proposals",
    "monthly_income_plans",
    "ocr_facts",
    "recurring_items",
    "repayment_drafts",
    "repayments",
)

# OCR extraction rows are replaceable suggestions. They participate in the
# adoption snapshot so a preview cannot silently cross an OCR update, but they
# are not a currency writer authority. Every authoritative OCR application also
# mutates the fenced parent expense in the same transaction.
CURRENCY_WRITER_FENCE_TABLES = tuple(
    table for table in CURRENCY_EVIDENCE_TABLES if table != "ocr_facts"
)

INSTALLATION_ADOPTION_OPERATION = "currency_binding_adoption"
INSTALLATION_IDEMPOTENCY_TTL_HOURS = 24
