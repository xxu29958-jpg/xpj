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


def _tenant_scoped_models() -> tuple[type, ...]:
    """Return every ORM model that carries a per-tenant ``tenant_id`` column.

    This list is the *single source of truth* for which tables should be
    swept when collecting historical tenant ids from legacy data. New
    tenant-scoped tables MUST be added here — otherwise their legacy rows
    never appear in the ``ensure_identity_for_existing_ledger_ids`` pass
    and identity-seeding leaves orphaned data behind.
    """
    from app.models import (
        Budget,
        BudgetCategory,
        CategoryRule,
        CsvImportBatch,
        CsvImportRow,
        DashboardCardPreference,
        DuplicateIgnore,
        ExchangeRate,
        Expense,
        ExpenseItem,
        ExpenseSplit,
        ExpenseTag,
        Goal,
        MerchantAlias,
        RuleApplicationBatch,
        RuleApplicationChange,
        Tag,
    )

    return (
        Expense,
        ExpenseItem,
        ExpenseSplit,
        CsvImportBatch,
        CsvImportRow,
        CategoryRule,
        MerchantAlias,
        Tag,
        ExpenseTag,
        DuplicateIgnore,
        Budget,
        BudgetCategory,
        ExchangeRate,
        Goal,
        DashboardCardPreference,
        RuleApplicationBatch,
        RuleApplicationChange,
    )


def seed_identity_data() -> None:
    from app.services.identity_service import ensure_identity_for_existing_ledger_ids, ensure_identity_seed

    with SessionLocal() as db:
        ensure_identity_seed(db)
        # Use the session's own connection for inspection. ``inspect(engine)``
        # opens an independent connection wrapper; under StaticPool (in-memory
        # tests) its release path rolls back the session's pending writes from
        # ``ensure_identity_seed`` because the underlying SQLite handle is
        # shared.
        existing = set(inspect(db.connection()).get_table_names())
        ids: set[str] = set()
        for model in _tenant_scoped_models():
            table_name = model.__tablename__
            if table_name not in existing:
                continue
            ids.update(
                str(value)
                for value in db.scalars(select(model.tenant_id).distinct())
                if value
            )
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
