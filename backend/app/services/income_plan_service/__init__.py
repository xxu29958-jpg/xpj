"""Income estimate commands, their current projection and monthly revision queries."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal, NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_filter, ledger_scoped_select
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.services.currency_binding_service import (
    resolve_write_capability,
)
from app.services.currency_common import normalize_currency_code
from app.services.income_plan_service._forecast import IncomeForecast, query_income_forecast
from app.services.income_plan_service._history import (
    append_income_revision,
    income_change_month,
    income_intent_month,
    income_month_start,
    require_forward_income_month,
    require_income_status_month,
)
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
) -> list[IncomePlanRevision]:
    """The declared whole-month estimates, including archived plans' earlier revisions."""
    return list(income_forecast(
        db, tenant_id=tenant_id, month=month, as_of=as_of, timezone_name=timezone_name,
    ).entries)


def income_forecast(
    db: Session, *, tenant_id: str, month: str, as_of: datetime | None = None,
    timezone_name: str | None = None,
) -> IncomeForecast:
    return query_income_forecast(
        db, tenant_id=tenant_id, period=income_month_start(month),
        today=_income_as_of_date(as_of=as_of, timezone_name=timezone_name),
    )


def create_income_plan(
    db: Session,
    *,
    tenant_id: str,
    label: str,
    source_type: str,
    home_currency_code: str,
    amount_cents: int,
    pay_day: int,
    frequency: str = "monthly",
    income_month: str | None = None,
    intent_month: str | None = None,
    actor_account_id: int | None = None,
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
    resolve_write_capability(db)
    home = normalize_currency_code(home_currency_code)

    when = now or now_utc()
    intent_period = income_intent_month(intent_month, when)
    period = income_change_month(
        current_frequency=None, current_income_month=None,
        frequency=clean_frequency, income_month=clean_income_month,
        period=intent_period,
    )
    row = MonthlyIncomePlan(
        tenant_id=tenant_id,
        label=clean_label,
        source_type=clean_source,
        frequency=clean_frequency,
        income_month=clean_income_month,
        home_currency_code=home,
        amount_cents=clean_amount_cents,
        pay_day=pay_day,
        status="active",
        created_at=when,
        updated_at=when,
    )
    db.add(row)
    db.flush()
    append_income_revision(
        db, row, period=period, intent_period=intent_period, change_kind="create", actor_account_id=actor_account_id, when=when,
    )
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
    intent_month: str | None = None,
    actor_account_id: int | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> MonthlyIncomePlan:
    """Partial update. Archived plans cannot be edited directly."""

    if amount_cents is not None:
        validate_income_plan_amount(amount_cents)
    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    _require_active_income_plan(plan)
    # R13-2：同 create —— 编辑写先过绑定门（漂移/未决拒写）。
    resolve_write_capability(db)

    when = now or now_utc()
    period = income_intent_month(intent_month, when)
    require_forward_income_month(db, plan, period)
    new_frequency = _updated_income_frequency(plan, frequency)
    new_income_month = _updated_income_month(
        plan, frequency=new_frequency, income_month=income_month, income_month_provided=income_month_provided,
    )
    effective_month = income_change_month(
        current_frequency=plan.frequency, current_income_month=plan.income_month,
        frequency=new_frequency, income_month=new_income_month, period=period,
    )
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
            "income_month": new_income_month,
            "amount_cents": _updated_income_amount_cents(plan, amount_cents),
            "pay_day": _updated_income_pay_day(plan, pay_day),
            "updated_at": when,
        },
        extra_where=(MonthlyIncomePlan.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        _raise_income_plan_edit_conflict(db, tenant_id=tenant_id, public_id=public_id)
    db.expire_all()
    current = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    append_income_revision(
        db, current, period=effective_month, intent_period=period, change_kind="edit", actor_account_id=actor_account_id, when=when,
    )
    if commit:
        db.commit()
    return current


def archive_income_plan(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    intent_month: str | None = None,
    actor_account_id: int | None = None,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Soft-delete an income row. Atomic optimistic concurrency."""

    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    when = now or now_utc()
    if plan.status == "archived":
        require_income_status_month(db, plan, income_intent_month(intent_month, when))
        return plan
    resolve_write_capability(db)
    period = income_intent_month(intent_month, when)
    require_forward_income_month(db, plan, period)
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
            require_income_status_month(db, current, period)
            return current
        raise AppError("state_conflict", status_code=409)
    db.expire_all()
    current = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    append_income_revision(
        db, current, period=period, intent_period=period, change_kind="archive", actor_account_id=actor_account_id, when=when,
    )
    db.commit()
    return current


def restore_income_plan(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    intent_month: str | None = None,
    actor_account_id: int | None = None,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Reactivate an archived income row. Atomic optimistic concurrency."""

    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    when = now or now_utc()
    if plan.status == "active":
        require_income_status_month(db, plan, income_intent_month(intent_month, when))
        return plan
    resolve_write_capability(db)
    period = income_intent_month(intent_month, when)
    require_forward_income_month(db, plan, period)
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
            require_income_status_month(db, current, period)
            return current
        raise AppError("state_conflict", status_code=409)
    db.expire_all()
    current = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    append_income_revision(
        db, current, period=period, intent_period=period, change_kind="restore", actor_account_id=actor_account_id, when=when,
    )
    db.commit()
    return current


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
    """Whole-month planned income; it is never a receipt or cash balance."""
    today = _income_as_of_date(as_of=as_of, timezone_name=timezone_name)
    forecast = query_income_forecast(
        db, tenant_id=tenant_id, period=income_month_start(month) if month else today.replace(day=1), today=today,
    )
    if forecast.expected_amount_cents is None:
        raise AppError("exchange_rate_missing", "部分收入计划缺少折算汇率，请补齐汇率后查看完整估算。", status_code=422)
    return forecast.expected_amount_cents


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
    return _normalize_month(income_month, field_label="预计月份")


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
            "预计收入日需在 1 到 31 之间。",
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
    "income_forecast",
    "list_applicable_income_plans",
    "list_income_plans",
    "restore_income_plan",
    "total_monthly_income_cents",
    "update_income_plan",
]
