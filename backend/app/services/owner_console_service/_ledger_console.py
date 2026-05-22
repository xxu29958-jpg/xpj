"""Ledger management view-models and operations for the Owner Console.

This module also owns the ledger-id discovery helpers
(``list_console_ledger_choices`` / ``_managed_console_ledger_ids`` /
``get_default_ledger_id``) because they all return the same
"ledgers the local owner can manage" set, just shaped differently for
different callers.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.services.data_quality_service import data_quality_summary
from app.services.ledger_service import (
    LedgerSummary,
    ledger_member_counts,
    list_ledgers_for_account,
    list_managed_ledgers_for_account,
)
from app.services.ledger_service import (
    create_ledger as ledger_service_create_ledger,
)
from app.services.owner_console_service._common import (
    get_owner_account_id,
    logger,
)


def list_console_ledger_choices(db: Session) -> list[LedgerSummary]:
    """Return owner-managed ledgers the pairing dropdown should show.

    Returns an empty list before bootstrap so the caller can render a clear
    "service not initialised" message instead of a blank dropdown.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    return list_managed_ledgers_for_account(db, account_id=owner_id)


def _managed_console_ledger_ids(db: Session) -> set[str]:
    return {ledger.ledger_id for ledger in list_console_ledger_choices(db)}


def get_default_ledger_id(db: Session) -> str | None:
    choices = list_console_ledger_choices(db)
    if not choices:
        return None
    default = next((ledger for ledger in choices if ledger.is_default), None)
    return (default or choices[0]).ledger_id


@dataclass
class LedgerHealthVM:
    """Per-ledger snapshot for the Owner Console dashboard health card.

    Counters mirror :class:`DataQualitySummary` but are scoped to one ledger
    so the owner can spot which ledger needs attention without opening each
    one individually. All values are read-only; the dashboard renders direct
    links to the matching /web pages.
    """

    ledger_id: str
    name: str
    is_default: bool
    pending: int
    ready_to_confirm: int
    suspected_duplicates: int
    missing_merchant: int
    missing_category: int
    oldest_pending_age_days: int | None


def list_ledger_health(db: Session) -> list[LedgerHealthVM]:
    """Compute :class:`LedgerHealthVM` for every ledger the owner owns.

    Reuses :func:`data_quality_summary` so the counters always match the
    /web/data-quality page exactly. Empty list when the owner has no
    ledgers yet (fresh install).
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    rows: list[LedgerHealthVM] = []
    for summary in list_managed_ledgers_for_account(db, account_id=owner_id):
        try:
            dq = data_quality_summary(db, tenant_id=summary.ledger_id)
        except Exception:  # noqa: BLE001 — one bad ledger must not hide the rest
            logger.exception("owner_console ledger_health: data_quality_summary failed for ledger=%s", summary.ledger_id)
            continue
        rows.append(
            LedgerHealthVM(
                ledger_id=summary.ledger_id,
                name=summary.name,
                is_default=summary.is_default,
                pending=dq.pending_total,
                ready_to_confirm=dq.ready_to_confirm,
                suspected_duplicates=dq.suspected_duplicates,
                missing_merchant=dq.missing_merchant,
                missing_category=dq.missing_category,
                oldest_pending_age_days=dq.oldest_pending_age_days,
            )
        )
    return rows


@dataclass
class LedgerConsoleVM:
    """View-model for a single ledger row in the Owner Console ledgers page.

    Counts are computed at display time; for v0.4-alpha1 the absolute numbers
    matter less than confirming each ledger has its own pending/confirmed
    bucket and that switching ledgers does not bleed counts across.
    """

    ledger_id: str
    name: str
    role: str
    is_default: bool
    pending_count: int
    confirmed_count: int
    active_device_count: int


def _ledger_console_rows(db: Session, summaries: list[LedgerSummary]) -> list[LedgerConsoleVM]:
    rows: list[LedgerConsoleVM] = []
    for summary in summaries:
        pending = int(
            db.scalar(
                select(func.count())
                .select_from(Expense)
                .where(Expense.tenant_id == summary.ledger_id)
                .where(Expense.status == "pending")
            )
            or 0
        )
        confirmed = int(
            db.scalar(
                select(func.count())
                .select_from(Expense)
                .where(Expense.tenant_id == summary.ledger_id)
                .where(Expense.status == "confirmed")
            )
            or 0
        )
        counts = ledger_member_counts(db, ledger_id=summary.ledger_id)
        rows.append(
            LedgerConsoleVM(
                ledger_id=summary.ledger_id,
                name=summary.name,
                role=summary.role,
                is_default=summary.is_default,
                pending_count=pending,
                confirmed_count=confirmed,
                active_device_count=counts["active_devices"],
            )
        )
    return rows


def list_console_ledgers(db: Session) -> list[LedgerConsoleVM]:
    """Return ledger rows visible to the local account.

    The /web progressive UI uses this read surface so member/viewer ledgers
    remain browsable. Management actions must use
    :func:`list_manageable_console_ledgers` or :func:`list_console_ledger_choices`.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    return _ledger_console_rows(db, list_ledgers_for_account(db, account_id=owner_id))


def list_manageable_console_ledgers(db: Session) -> list[LedgerConsoleVM]:
    """Return ledger rows the local account can manage as owner."""
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    return _ledger_console_rows(
        db,
        list_managed_ledgers_for_account(db, account_id=owner_id),
    )


def do_create_ledger(db: Session, *, name: str) -> LedgerSummary:
    """Create a new ledger owned by the local owner account.

    Owner Console runs as the local owner; we look up that account here so
    the route handler stays free of identity logic.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        raise AppError(
            "invalid_request",
            "服务未初始化，请先运行 bootstrap_dev_owner.ps1。",
            status_code=409,
        )
    return ledger_service_create_ledger(db, account_id=owner_id, name=name)
