"""Read-only expense lookups."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.services.spending_contract_service import confirmed_ordered, confirmed_query

__all__ = ["get_expense", "list_confirmed", "list_expenses_by_ids", "list_pending"]


def get_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense


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
