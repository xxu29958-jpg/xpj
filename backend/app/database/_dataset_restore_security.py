"""Closed restore-security classification for every registered database table."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

RestoreTableSecurity = Literal["preserve", "sanitize", "filter"]

# Insertion order for ``sanitize`` is the deletion order: dependent capability
# rows precede the principals/locks they reference.  The registry test requires
# every new SQLAlchemy table to receive an explicit classification before ship.
RESTORE_TABLE_SECURITY: Mapping[str, RestoreTableSecurity] = MappingProxyType(
    {
        "desktop_activation_attempts": "sanitize",
        "session_refresh_attempts": "sanitize",
        "auth_tokens": "sanitize",
        "device_enrollment_attempts": "sanitize",
        "installation_owner_claims": "sanitize",
        "bootstrap_secret_consumptions": "sanitize",
        "upload_link_daily_usage": "sanitize",
        "upload_link_remote_attempts": "sanitize",
        "upload_links": "sanitize",
        "pairing_attempt_failures": "sanitize",
        "pairing_codes": "sanitize",
        "invitations": "sanitize",
        "installation_idempotency_keys": "sanitize",
        "scheduler_leases": "sanitize",
        "budget_advisor_quota_locks": "sanitize",
        "ai_transaction_temp_id_map": "sanitize",
        "app_meta": "filter",
        "accounts": "preserve",
        "ai_member_anon_map": "preserve",
        "ai_merchant_anon_map": "preserve",
        "algorithm_decisions": "preserve",
        "api_idempotency_keys": "preserve",
        "background_tasks": "preserve",
        "bill_split_invitations": "preserve",
        "budget_advisor_audit_logs": "preserve",
        "budget_categories": "preserve",
        "budgets": "preserve",
        "category_preferences": "preserve",
        "category_rules": "preserve",
        "csv_import_batches": "preserve",
        "csv_import_rows": "preserve",
        "dashboard_card_preferences": "preserve",
        "dataset_authority": "preserve",
        "debt_adjustments": "preserve",
        "debt_forgivenesses": "preserve",
        "debt_goal_links": "preserve",
        "debt_voids": "preserve",
        "debts": "preserve",
        "devices": "preserve",
        "duplicate_ignores": "preserve",
        "exchange_rates": "preserve",
        "expense_items": "preserve",
        "expense_offset_facts": "preserve",
        "expense_offset_revisions": "preserve",
        "expense_revisions": "preserve",
        "expense_splits": "preserve",
        "expense_tags": "preserve",
        "expenses": "preserve",
        "fx_rates": "preserve",
        "goals": "preserve",
        "installation_currency_audit_log": "preserve",
        "installation_currency_bindings": "preserve",
        "ledger_audit_logs": "preserve",
        "ledger_learning_events": "preserve",
        "ledger_members": "preserve",
        "ledgers": "preserve",
        "member_repayment_proposals": "preserve",
        "merchant_aliases": "preserve",
        "merchant_catalog": "preserve",
        "monthly_income_plans": "preserve",
        "ocr_facts": "preserve",
        "recurring_items": "preserve",
        "repayment_drafts": "preserve",
        "repayment_voids": "preserve",
        "repayments": "preserve",
        "rule_application_batches": "preserve",
        "rule_application_changes": "preserve",
        "schema_migrations": "preserve",
        "tag_mutation_undo_groups": "preserve",
        "tag_mutation_undo_items": "preserve",
        "tags": "preserve",
    }
)

SANITATION_TABLES: tuple[str, ...] = tuple(
    table
    for table, classification in RESTORE_TABLE_SECURITY.items()
    if classification == "sanitize"
)

__all__ = ["RESTORE_TABLE_SECURITY", "SANITATION_TABLES", "RestoreTableSecurity"]
