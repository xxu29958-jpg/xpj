from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.sql import ColumnElement, Select

ModelT = TypeVar("ModelT")


def ledger_filter(model: type[ModelT], tenant_id: str) -> ColumnElement[bool]:
    """Return the mandatory ledger predicate for tenant-scoped ORM models.

    The database column is still named ``tenant_id`` for compatibility, but its
    runtime meaning is ``ledger_id``. New Expense/CategoryRule/MerchantAlias/
    DuplicateIgnore/RecurringItem queries should use this helper or an
    equivalent explicit ``Model.tenant_id == tenant_id`` predicate.
    """
    column = getattr(model, "tenant_id", None)
    if column is None:
        raise TypeError(f"{model.__name__} is not ledger-scoped")
    return column == tenant_id


def ledger_scoped_select(model: type[ModelT], tenant_id: str) -> Select[Any]:
    return select(model).where(ledger_filter(model, tenant_id))


def add_ledger_scope(
    statement: Select[Any], model: type[ModelT], tenant_id: str
) -> Select[Any]:
    return statement.where(ledger_filter(model, tenant_id))
