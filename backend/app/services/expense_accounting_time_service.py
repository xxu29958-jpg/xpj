"""Apply calendar evidence inside the existing Expense command transaction."""

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.services.accounting_time_service import (
    apply_accounting_time,
    legacy_accounting_time,
    resolve_accounting_time,
)
from app.services.ledger_calendar_service import calendar_revision
from app.services.time_service import ensure_utc


def _required_rule(db: Session, expense: Expense, revision: int):
    rule = calendar_revision(db, ledger_id=expense.tenant_id, revision=revision)
    if rule is None:
        raise AppError("calendar_revision_conflict", "未找到原输入使用的账务日历，请保留输入后重试。", status_code=409)
    return rule


def _transaction_time(expense: Expense):
    """Accounting-period or source-zone edits alone do not re-price a frozen quote."""
    if expense.time_precision == "date_only":
        return "date_only", expense.user_local_date
    return "instant", ensure_utc(expense.expense_time)


def apply_expense_time_input(db: Session, expense: Expense, payload, *, creating: bool = False) -> bool:
    """Return whether actual transaction time changed, without touching OCC or commit.

    Missing/null time_input means no new value object was supplied. Legacy
    timestamp fields retain their explicit-null clearing semantics and original
    request fingerprint. An unchanged old timestamp preserves richer evidence.
    """
    before = _transaction_time(expense)
    value = payload.time_input
    fields = payload.model_fields_set
    if value is not None:
        for alias in {"spent_at", "expense_time"} & fields:
            if ensure_utc(getattr(payload, alias)) != ensure_utc(value.instant_utc):
                raise AppError("accounting_time_invalid", "时间输入互相矛盾，请核对原输入。", status_code=422)
        rule = _required_rule(db, expense, value.calendar_revision)
        snapshot = resolve_accounting_time(value, ledger_timezone=rule.timezone_name, calendar_revision=rule.revision)
    else:
        aliases = {"spent_at", "expense_time"} & fields
        if not creating and not aliases:
            return False
        instant = ensure_utc(payload.spent_at if "spent_at" in fields else payload.expense_time)
        if not creating and instant == ensure_utc(expense.expense_time) and expense.calendar_revision is not None:
            return False
        if creating:
            instant = expense.expense_time
        rule = _required_rule(db, expense, 1)
        snapshot = legacy_accounting_time(expense_time=instant, confirmed_at=expense.confirmed_at,
            ledger_timezone=rule.timezone_name, calendar_revision=rule.revision)
    apply_accounting_time(expense, snapshot)
    return before != _transaction_time(expense)


def refresh_legacy_expense_time(db: Session, expense: Expense) -> None:
    """Freeze a legacy producer or confirmation fallback without changing known intent."""
    if expense.time_precision in {"instant", "date_only"}:
        return
    rule = _required_rule(db, expense, expense.calendar_revision or 1)
    apply_accounting_time(expense, legacy_accounting_time(expense_time=expense.expense_time,
        confirmed_at=expense.confirmed_at, ledger_timezone=rule.timezone_name, calendar_revision=rule.revision))
