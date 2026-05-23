"""Read-only expense lookups + lifecycle constants shared across services.

Sits below ``expense_service`` and ``receipt_item_service`` so both can
import from here without forming an import cycle.

``expense_service`` re-exports ``get_expense`` and ``EDITABLE_STATUSES``
from this module so existing call sites
(``from app.services.expense_service import EDITABLE_STATUSES, get_expense``)
keep working unchanged.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense

__all__ = ["EDITABLE_STATUSES", "get_expense"]


# An Expense is editable while ``pending`` (draft) or ``confirmed``
# (user-owned). Anything else (``rejected``, ``deleted``) is frozen.
EDITABLE_STATUSES = {"pending", "confirmed"}


def get_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense
