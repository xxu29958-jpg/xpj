"""User-declared income plan / income-entry service.

Rows in ``monthly_income_plans`` now cover two user-facing rhythms:

* ``monthly``: fixed income that applies to every accounting month.
* ``one_time``: a single income amount that applies only to ``income_month``.

The table name is kept for compatibility with existing migrations and clients,
but all aggregation entry points now accept a month when one-time income should
be included.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal, NoReturn

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import add_ledger_scope, ledger_filter, ledger_scoped_select
from app.models import MonthlyIncomePlan
from app.money_contract import projection_sum_to_int
from app.services.currency_binding_service import (
    assert_currency_binding_consistent,
    resolve_write_capability,
)
from app.services.currency_common import home_currency_code
from app.services.income_plan_service._money import (
    updated_income_amount_cents as _updated_income_amount_cents,
)
from app.services.income_plan_service._money import validate_income_plan_amount
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import ensure_utc, now_utc, safe_zone

IncomeStatus = Literal["active", "archived"]
IncomeFrequency = Literal["monthly", "one_time"]

_LABEL_MAX_LEN = 64
_SOURCE_TYPE_MAX_LEN = 32
_FREQUENCIES = {"monthly", "one_time"}
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def list_income_plans(
    db: Session,
    *,
    tenant_id: str,
    status: IncomeStatus | None = "active",
) -> list[MonthlyIncomePlan]:
    """Return income rows for the tenant.

    Defaults to active rows. Pass ``status=None`` for management screens that
    need both active and archived rows. This is intentionally not month-filtered:
    users should still be able to see, archive, or restore old one-time income.
    """

    statement = _income_plan_base_select(tenant_id=tenant_id)
    if status is not None:
        statement = statement.where(MonthlyIncomePlan.status == status)
    return list(db.scalars(statement))


def list_applicable_income_plans(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    as_of: datetime | None = None,
    timezone_name: str | None = None,
) -> list[MonthlyIncomePlan]:
    """Active income rows that should count for ``month``.

    For the current accounting month, rows are counted only after their
    pay/arrival day has passed. A month-end salary should not inflate
    today's spendable amount before it actually lands.
    """

    clean_month = _normalize_month(month, field_label="月份")
    as_of_date = _income_as_of_date(as_of=as_of, timezone_name=timezone_name)
    statement = (
        _income_plan_base_select(tenant_id=tenant_id)
        .where(MonthlyIncomePlan.status == "active")
        .where(_applicable_income_clause(clean_month, as_of_date=as_of_date))
    )
    return list(db.scalars(statement))


def create_income_plan(
    db: Session,
    *,
    tenant_id: str,
    label: str,
    source_type: str,
    amount_cents: int,
    pay_day: int,
    frequency: str = "monthly",
    income_month: str | None = None,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Insert a new active income row."""

    clean_amount_cents = validate_income_plan_amount(amount_cents)
    clean_label = _clean_label(label)
    clean_source = _clean_source_type(source_type)
    clean_frequency = _clean_frequency(frequency)
    clean_income_month = _normalize_income_month(
        frequency=clean_frequency,
        income_month=income_month,
    )
    _validate_pay_day(pay_day)
    # R13-2：无币种列的收入计划写按 env 口径入账 —— 先过绑定门（漂移/未决拒写）。
    assert_currency_binding_consistent(db, home_currency_code())

    when = now or now_utc()
    row = MonthlyIncomePlan(
        tenant_id=tenant_id,
        label=clean_label,
        source_type=clean_source,
        frequency=clean_frequency,
        income_month=clean_income_month,
        amount_cents=clean_amount_cents,
        pay_day=pay_day,
        status="active",
        created_at=when,
        updated_at=when,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_income_plan(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    label: str | None = None,
    source_type: str | None = None,
    amount_cents: int | None = None,
    pay_day: int | None = None,
    frequency: str | None = None,
    income_month: str | None = None,
    income_month_provided: bool = False,
    now: datetime | None = None,
    commit: bool = True,
) -> MonthlyIncomePlan:
    """Partial update. Archived plans cannot be edited directly."""

    if amount_cents is not None:
        validate_income_plan_amount(amount_cents)
    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    _require_active_income_plan(plan)
    # R13-2：同 create —— 编辑写先过绑定门（漂移/未决拒写）。
    assert_currency_binding_consistent(db, home_currency_code())

    when = now or now_utc()
    new_frequency = _updated_income_frequency(plan, frequency)
    rowcount = claim_row_with_token(
        db,
        MonthlyIncomePlan,
        pk_id=plan.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={
            "label": _updated_income_label(plan, label),
            "source_type": _updated_income_source_type(plan, source_type),
            "frequency": new_frequency,
            "income_month": _updated_income_month(
                plan,
                frequency=new_frequency,
                income_month=income_month,
                income_month_provided=income_month_provided,
            ),
            "amount_cents": _updated_income_amount_cents(plan, amount_cents),
            "pay_day": _updated_income_pay_day(plan, pay_day),
            "updated_at": when,
        },
        extra_where=(MonthlyIncomePlan.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        _raise_income_plan_edit_conflict(db, tenant_id=tenant_id, public_id=public_id)
    if commit:
        db.commit()
    else:
        db.flush()
    db.expire_all()
    return _require_plan(db, tenant_id=tenant_id, public_id=public_id)


def archive_income_plan(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Soft-delete an income row. Atomic optimistic concurrency."""

    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    if plan.status == "archived":
        return plan
    resolve_write_capability(db)
    when = now or now_utc()
    rowcount = claim_row_with_token(
        db,
        MonthlyIncomePlan,
        pk_id=plan.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"status": "archived", "archived_at": when, "updated_at": when},
        extra_where=(MonthlyIncomePlan.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
        if current.status == "archived":
            return current
        raise AppError("state_conflict", status_code=409)
    db.commit()
    db.expire_all()
    return _require_plan(db, tenant_id=tenant_id, public_id=public_id)


def restore_income_plan(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Reactivate an archived income row. Atomic optimistic concurrency."""

    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    if plan.status == "active":
        return plan
    resolve_write_capability(db)
    when = now or now_utc()
    rowcount = claim_row_with_token(
        db,
        MonthlyIncomePlan,
        pk_id=plan.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"status": "active", "archived_at": None, "updated_at": when},
        extra_where=(MonthlyIncomePlan.status == "archived",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
        if current.status == "active":
            return current
        raise AppError("state_conflict", status_code=409)
    db.commit()
    db.expire_all()
    return _require_plan(db, tenant_id=tenant_id, public_id=public_id)


def get_income_plan(db: Session, *, tenant_id: str, public_id: str) -> MonthlyIncomePlan:
    """Tenant-scoped single read (404 when absent)."""

    return _require_plan(db, tenant_id=tenant_id, public_id=public_id)


def total_monthly_income_cents(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    as_of: datetime | None = None,
    timezone_name: str | None = None,
) -> int:
    """Sum active income for the monthly discretionary formula.

    Without ``month``, only recurring monthly rows are counted. With ``month``,
    rows are additionally gated by the local as-of date so a month-end salary is
    not treated as available before payday.
    """

    clean_month = _normalize_month(month, field_label="月份") if month else None
    as_of_date = _income_as_of_date(as_of=as_of, timezone_name=timezone_name) if clean_month is not None else None
    statement = add_ledger_scope(
        select(func.coalesce(func.sum(MonthlyIncomePlan.amount_cents), 0)),
        MonthlyIncomePlan,
        tenant_id,
    ).where(MonthlyIncomePlan.status == "active")
    statement = statement.where(_applicable_income_clause(clean_month, as_of_date=as_of_date))
    total = db.scalar(statement)
    return projection_sum_to_int(
        total,
        label="income_plan.total",
    )


def _require_active_income_plan(plan: MonthlyIncomePlan) -> None:
    if plan.status == "archived":
        raise AppError(
            "state_conflict",
            "已归档的收入不能直接修改，请先恢复。",
            status_code=409,
        )


def _updated_income_label(plan: MonthlyIncomePlan, label: str | None) -> str:
    if label is None:
        return plan.label
    return _clean_label(label)


def _updated_income_source_type(plan: MonthlyIncomePlan, source_type: str | None) -> str:
    if source_type is None:
        return plan.source_type
    return _clean_source_type(source_type)


def _updated_income_pay_day(plan: MonthlyIncomePlan, pay_day: int | None) -> int:
    if pay_day is None:
        return plan.pay_day
    _validate_pay_day(pay_day)
    return pay_day


def _updated_income_frequency(plan: MonthlyIncomePlan, frequency: str | None) -> IncomeFrequency:
    if frequency is None:
        return plan.frequency or "monthly"  # type: ignore[return-value]
    return _clean_frequency(frequency)


def _updated_income_month(
    plan: MonthlyIncomePlan,
    *,
    frequency: str,
    income_month: str | None,
    income_month_provided: bool,
) -> str | None:
    selected_income_month = income_month if income_month_provided else plan.income_month
    return _normalize_income_month(
        frequency=frequency,
        income_month=selected_income_month,
    )


def _raise_income_plan_edit_conflict(db: Session, *, tenant_id: str, public_id: str) -> NoReturn:
    db.rollback()
    current = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    if current.status == "archived":
        raise AppError(
            "state_conflict",
            "已归档的收入不能直接修改，请先恢复。",
            status_code=409,
        )
    raise AppError("state_conflict", status_code=409)


def _income_plan_base_select(*, tenant_id: str):
    return ledger_scoped_select(MonthlyIncomePlan, tenant_id).order_by(
        MonthlyIncomePlan.frequency.asc(),
        MonthlyIncomePlan.income_month.asc(),
        MonthlyIncomePlan.pay_day.asc(),
        MonthlyIncomePlan.id.asc(),
    )


def _applicable_income_clause(month: str | None, *, as_of_date: date | None = None):
    if month is None:
        return MonthlyIncomePlan.frequency == "monthly"
    timing_clause = _income_timing_clause(month=month, as_of_date=as_of_date)
    return or_(
        and_(MonthlyIncomePlan.frequency == "monthly", timing_clause),
        and_(
            MonthlyIncomePlan.frequency == "one_time",
            MonthlyIncomePlan.income_month == month,
            timing_clause,
        ),
    )


def _income_timing_clause(*, month: str, as_of_date: date | None):
    if as_of_date is None:
        return True
    year_text, month_text = month.split("-", maxsplit=1)
    target_index = int(year_text) * 12 + int(month_text)
    as_of_index = as_of_date.year * 12 + as_of_date.month
    if target_index < as_of_index:
        return True
    if target_index > as_of_index:
        return false()
    return MonthlyIncomePlan.pay_day <= as_of_date.day


def _income_as_of_date(
    *,
    as_of: datetime | None,
    timezone_name: str | None,
) -> date:
    zone = safe_zone((timezone_name or "").strip() or get_settings().ocr_default_timezone)
    return ensure_utc(as_of or now_utc()).astimezone(zone).date()


def _clean_label(label: str) -> str:
    clean_label = (label or "").strip()
    if not clean_label:
        raise AppError("invalid_request", "请填写收入名称。", status_code=422)
    if len(clean_label) > _LABEL_MAX_LEN:
        raise AppError(
            "invalid_request",
            f"收入名称最多 {_LABEL_MAX_LEN} 个字符。",
            status_code=422,
        )
    return clean_label


def _clean_source_type(source_type: str | None) -> str:
    return (source_type or "salary").strip()[:_SOURCE_TYPE_MAX_LEN] or "salary"


def _clean_frequency(frequency: str | None) -> IncomeFrequency:
    normalized = (frequency or "monthly").strip().lower()
    if normalized not in _FREQUENCIES:
        raise AppError(
            "invalid_request",
            "请选择正确的收入类型。",
            status_code=422,
        )
    return normalized  # type: ignore[return-value]


def _normalize_income_month(*, frequency: str, income_month: str | None) -> str | None:
    if frequency == "monthly":
        return None
    return _normalize_month(income_month, field_label="到账月份")


def _normalize_month(value: str | None, *, field_label: str) -> str:
    text = (value or "").strip()
    if not _MONTH_RE.fullmatch(text):
        raise AppError(
            "invalid_request",
            f"请选择正确的{field_label}。",
            status_code=422,
        )
    return text


def _validate_pay_day(pay_day: int) -> None:
    if not 1 <= pay_day <= 31:
        raise AppError(
            "invalid_request",
            "发薪日/到账日需在 1 到 31 之间。",
            status_code=422,
        )


def _require_plan(db: Session, *, tenant_id: str, public_id: str) -> MonthlyIncomePlan:
    plan = db.scalar(
        select(MonthlyIncomePlan)
        .where(ledger_filter(MonthlyIncomePlan, tenant_id))
        .where(MonthlyIncomePlan.public_id == public_id)
        .limit(1)
    )
    if plan is None:
        raise AppError("not_found", "收入不存在。", status_code=404)
    return plan


__all__ = [
    "IncomeFrequency",
    "IncomeStatus",
    "archive_income_plan",
    "create_income_plan",
    "get_income_plan",
    "list_applicable_income_plans",
    "list_income_plans",
    "restore_income_plan",
    "total_monthly_income_cents",
    "update_income_plan",
]
