"""Suspected-duplicate listing and manual override."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Expense
from app.services.duplicate_service import list_suspected_duplicates, mark_not_duplicate
from app.services.expense_service._query import get_expense
from app.services.time_service import now_utc


__all__ = ["list_duplicate_expenses", "mark_expense_not_duplicate"]


def list_duplicate_expenses(db: Session, tenant_id: str) -> list[Expense]:
    return list_suspected_duplicates(db, tenant_id)


def mark_expense_not_duplicate(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = get_expense(db, expense_id, tenant_id)
    mark_not_duplicate(db, expense)
    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense
