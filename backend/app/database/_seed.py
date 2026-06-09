"""Seed legacy and runtime data after the schema is materialized.

These functions only ever run from :func:`app.database.init_db`. They touch
identity tables, default category rules, and per-tenant normalization that
the rest of the app assumes is already in place by the time a request
arrives.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import inspect, select, text

from app.database._core import SessionLocal, engine
from app.database._tenant_id_check import _validate_legacy_tenant_ids
from app.version import BACKEND_VERSION

__all__ = [
    "BASELINE_MIGRATION_NAME",
    "reconcile_expense_tag_mirror_once",
    "record_schema_migration",
    "seed_identity_data",
    "seed_runtime_data",
]

# ADR-0043 slice A: marker for the one-time expense_tags mirror reconcile.
_TAG_MIRROR_RECONCILE_MARKER = "tag-mirror-reconcile-v1"

# Baseline marker recorded once per startup into the schema_migrations ledger
# (backup/restore validators match its backend_version). Relocated here when
# the SQLite startup migrator that formerly owned it was retired (PG-only).
BASELINE_MIGRATION_NAME = f"baseline-v{BACKEND_VERSION}"


def record_schema_migration(
    name: str,
    *,
    backend_version: str | None = None,
    note: str | None = None,
) -> None:
    """Record that the named migration step has been applied.

    Idempotent: re-recording the same name is a no-op. ``backend_version``
    is what backup/restore validators match against — leaving it None means
    the row will not satisfy ``--expected-backend-version`` checks.
    """

    # Portable "insert if absent": check-then-insert instead of SQLite-only
    # ``INSERT OR IGNORE`` (PostgreSQL would reject that syntax). Runs once
    # per startup in a single process, so the TOCTOU gap is not a real race.
    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :name LIMIT 1"),
            {"name": name},
        ).first()
        if existing is not None:
            return
        connection.execute(
            text(
                "INSERT INTO schema_migrations "
                "(name, applied_at, backend_version, note) "
                "VALUES (:name, :applied_at, :backend_version, :note)"
            ),
            {
                "name": name,
                "applied_at": datetime.now(UTC),
                "backend_version": backend_version,
                "note": note,
            },
        )


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
        TagMutationUndoGroup,
        TagMutationUndoItem,
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
        TagMutationUndoGroup,
        TagMutationUndoItem,
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
        # Inspect via the session's own connection, not ``inspect(engine)``:
        # the latter opens an independent connection (a separate transaction)
        # that can't see schema/rows still uncommitted in this session's
        # transaction — which the PG per-test rollback-isolation lane relies on.
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


def _tag_mirror_reconcile_done() -> bool:
    """Cross-dialect 'already reconciled' check.

    Reads the ``schema_migrations`` ledger directly so it behaves identically on
    either engine — the reconcile must run exactly once, not on every startup.
    """
    with engine.connect() as connection:
        if "schema_migrations" not in set(inspect(connection).get_table_names()):
            return False
        row = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :name LIMIT 1"),
            {"name": _TAG_MIRROR_RECONCILE_MARKER},
        ).first()
    return row is not None


def reconcile_expense_tag_mirror_once() -> None:
    """One-time ADR-0043 ``expense_tags`` mirror repair across every ledger.

    Runs after the schema migration (columns exist on both dialects) and
    once-only via a ``schema_migrations`` marker — the per-startup seed passes
    above can't host an unbounded full-table scan. Crash-safe: each ledger's
    batches commit independently and the marker is recorded only after the full
    sweep, so a crash mid-sweep leaves the marker absent and the next boot
    re-sweeps every ledger — already-repaired rows are a no-op (drift = False).
    """
    if _tag_mirror_reconcile_done():
        return
    from app.services.identity_service import ledger_ids
    from app.services.tag_service import reconcile_expense_tag_mirror

    with SessionLocal() as db:
        for ledger_id in ledger_ids(db):
            reconcile_expense_tag_mirror(db, ledger_id)
    record_schema_migration(
        _TAG_MIRROR_RECONCILE_MARKER,
        backend_version=BACKEND_VERSION,
        note="ADR-0043 expense_tags mirror reconcile",
    )
