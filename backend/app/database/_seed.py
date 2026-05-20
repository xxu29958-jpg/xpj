"""Seed legacy and runtime data after the schema is materialized.

These functions only ever run from :func:`app.database.init_db`. They touch
identity tables, default category rules, and per-tenant normalization that
the rest of the app assumes is already in place by the time a request
arrives.
"""

from __future__ import annotations

from sqlalchemy import inspect, select

from app.database._core import SessionLocal
from app.database._validate import _validate_legacy_tenant_ids


__all__ = ["seed_identity_data", "seed_runtime_data"]


def seed_identity_data() -> None:
    from app.models import (
        Budget,
        BudgetCategory,
        CategoryRule,
        CsvImportBatch,
        CsvImportRow,
        DashboardCardPreference,
        DuplicateIgnore,
        Expense,
        ExpenseItem,
        ExpenseSplit,
        ExpenseTag,
        ExchangeRate,
        Goal,
        MerchantAlias,
        RuleApplicationBatch,
        RuleApplicationChange,
        Tag,
    )
    from app.services.identity_service import ensure_identity_for_existing_ledger_ids, ensure_identity_seed

    with SessionLocal() as db:
        ensure_identity_seed(db)
        # Use the session's own connection for inspection. Using
        # ``inspect(engine)`` here opens an independent connection wrapper;
        # under StaticPool (in-memory tests) that wrapper's release path
        # rolls back the session's in-progress writes from
        # ``ensure_identity_seed`` because it shares the underlying SQLite
        # connection.
        inspector = inspect(db.connection())
        existing = set(inspector.get_table_names())
        ids: set[str] = set()
        if "expenses" in existing:
            ids.update(str(value) for value in db.scalars(select(Expense.tenant_id).distinct()) if value)
        if "expense_items" in existing:
            ids.update(str(value) for value in db.scalars(select(ExpenseItem.tenant_id).distinct()) if value)
        if "expense_splits" in existing:
            ids.update(str(value) for value in db.scalars(select(ExpenseSplit.tenant_id).distinct()) if value)
        if "csv_import_batches" in existing:
            ids.update(str(value) for value in db.scalars(select(CsvImportBatch.tenant_id).distinct()) if value)
        if "csv_import_rows" in existing:
            ids.update(str(value) for value in db.scalars(select(CsvImportRow.tenant_id).distinct()) if value)
        if "category_rules" in existing:
            ids.update(str(value) for value in db.scalars(select(CategoryRule.tenant_id).distinct()) if value)
        if "merchant_aliases" in existing:
            ids.update(str(value) for value in db.scalars(select(MerchantAlias.tenant_id).distinct()) if value)
        if "tags" in existing:
            ids.update(str(value) for value in db.scalars(select(Tag.tenant_id).distinct()) if value)
        if "expense_tags" in existing:
            ids.update(str(value) for value in db.scalars(select(ExpenseTag.tenant_id).distinct()) if value)
        if "duplicate_ignores" in existing:
            ids.update(str(value) for value in db.scalars(select(DuplicateIgnore.tenant_id).distinct()) if value)
        if "budgets" in existing:
            ids.update(str(value) for value in db.scalars(select(Budget.tenant_id).distinct()) if value)
        if "budget_categories" in existing:
            ids.update(str(value) for value in db.scalars(select(BudgetCategory.tenant_id).distinct()) if value)
        if "exchange_rates" in existing:
            ids.update(str(value) for value in db.scalars(select(ExchangeRate.tenant_id).distinct()) if value)
        if "goals" in existing:
            ids.update(str(value) for value in db.scalars(select(Goal.tenant_id).distinct()) if value)
        if "dashboard_card_preferences" in existing:
            ids.update(
                str(value)
                for value in db.scalars(
                    select(DashboardCardPreference.tenant_id).distinct()
                )
                if value
            )
        if "rule_application_batches" in existing:
            ids.update(str(value) for value in db.scalars(select(RuleApplicationBatch.tenant_id).distinct()) if value)
        if "rule_application_changes" in existing:
            ids.update(str(value) for value in db.scalars(select(RuleApplicationChange.tenant_id).distinct()) if value)
        _validate_legacy_tenant_ids(ids, source="tenant-scoped tables")
        if ids:
            ensure_identity_for_existing_ledger_ids(db, ids)
        db.commit()


def seed_runtime_data() -> None:
    from app.services.category_service import normalize_existing_expense_categories
    from app.services.classify_service import seed_default_rules
    from app.services.identity_service import ledger_ids
    from app.services.tag_service import backfill_expense_tags

    with SessionLocal() as db:
        for ledger_id in ledger_ids(db):
            normalize_existing_expense_categories(db, ledger_id)
            backfill_expense_tags(db, ledger_id)
            seed_default_rules(db, ledger_id)
