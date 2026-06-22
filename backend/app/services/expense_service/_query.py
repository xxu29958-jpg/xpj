"""Read-only expense lookups."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.services.expense_query import (  # noqa: F401 — re-exported
    get_expense,
    resolve_expense,
)
from app.services.spending_contract_service import confirmed_ordered, confirmed_query

__all__ = [
    "fetch_expense_row_version_in_status",
    "get_expense",
    "is_expense_in_status_for_tenant",
    "ledger_has_any_expense",
    "list_confirmed",
    "list_expenses_by_ids",
    "list_pending",
    "resolve_expense",
]


def ledger_has_any_expense(db: Session, tenant_id: str) -> bool:
    """Cheap predicate: does this ledger have *any* expense row ever (any status)?

    Drives the /web dashboard first-day onboarding branch — a brand-new ledger
    with zero lifetime expenses gets directional guidance (where to add the first
    receipt) instead of a screen full of zeros. Lifetime (not this-month) scope is
    deliberate: a ledger that had expenses last month but none this month is NOT
    first-day, so the month-scoped ``confirmed_count`` / ``pending_count`` already
    in the dashboard payload can't answer this. ``LIMIT 1`` keeps it an existence
    probe, not a count over the whole table.
    """
    return (
        db.scalar(
            ledger_scoped_select(Expense, tenant_id)
            .with_only_columns(Expense.id)
            .limit(1)
        )
        is not None
    )


def is_expense_in_status_for_tenant(
    db: Session, *, expense_id: int, tenant_id: str, status: str
) -> bool:
    """Cheap predicate: does this expense exist in [status] under [tenant_id].

    ADR-0038 /web undo: the pending.html banner uses this to decide whether the
    ``?undo=<id>`` query in the URL is still meaningful (right ledger, still
    rejected, not yet purged). Soft affordance — the atomic UPDATE in
    ``undo_reject_expense`` is the real authority; this is the page telling
    the truth rather than rendering a misleading "可撤销" button.
    """
    return (
        db.scalar(
            ledger_scoped_select(Expense, tenant_id)
            .with_only_columns(Expense.id)
            .where(Expense.id == expense_id)
            .where(Expense.status == status)
            .limit(1)
        )
        is not None
    )


def fetch_expense_row_version_in_status(
    db: Session, *, expense_id: int, tenant_id: str, status: str
) -> int | None:
    """ADR-0041: return the row's ``row_version`` if it's in [status] under
    [tenant_id], else None. Used by ``/web/pending`` to seed the undo banner's
    hidden ``expected_row_version`` form field — without it the banner POSTs a
    body the server can't validate.

    Combines "is it still rejected?" with "what's its CAS token?" in one query
    so the ownership check and token read stay consistent (no TOCTOU between the
    predicate and a separate token fetch)."""
    return db.scalar(
        ledger_scoped_select(Expense, tenant_id)
        .with_only_columns(Expense.row_version)
        .where(Expense.id == expense_id)
        .where(Expense.status == status)
        .limit(1)
    )


def list_pending(db: Session, tenant_id: str) -> list[Expense]:
    return list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == "pending")
            .order_by(Expense.created_at.desc(), Expense.id.desc())
        )
    )


def list_expenses_by_ids(
    db: Session, *, tenant_id: str, expense_ids: list[int]
) -> list[Expense]:
    """Fetch ledger-scoped expenses by primary key ids.

    Cross-ledger ids are silently filtered out (caller decides how to surface
    that via len() comparison). The order of results is not guaranteed.
    """
    if not expense_ids:
        return []
    return list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id.in_(expense_ids))
        )
    )


def list_confirmed(
    db: Session,
    *,
    tenant_id: str,
    page: int = 1,
    page_size: int = 50,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> tuple[list[Expense], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)

    query = confirmed_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    expenses = list(
        db.scalars(
            confirmed_ordered(query).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return expenses, total
