"""User-declared monthly income plan service.

Tenant-scoped CRUD over :class:`MonthlyIncomePlan` plus a single
aggregate read (``total_monthly_income_cents``) consumed by the v1.1
"本月可自由支配" formula. No detection — income arrives in too many
shapes to infer safely; the user types each line.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import add_ledger_scope, ledger_filter, ledger_scoped_select
from app.models import MonthlyIncomePlan
from app.services.time_service import now_utc

IncomeStatus = Literal["active", "archived"]

_LABEL_MAX_LEN = 64
_SOURCE_TYPE_MAX_LEN = 32


def list_income_plans(
    db: Session,
    *,
    tenant_id: str,
    status: IncomeStatus | None = "active",
) -> list[MonthlyIncomePlan]:
    """Return income plans for the tenant. Defaults to ``active`` only;
    pass ``status=None`` for everything (e.g. management screens)."""

    statement = ledger_scoped_select(MonthlyIncomePlan, tenant_id).order_by(
        MonthlyIncomePlan.pay_day.asc(), MonthlyIncomePlan.id.asc()
    )
    if status is not None:
        statement = statement.where(MonthlyIncomePlan.status == status)
    return list(db.scalars(statement))


def create_income_plan(
    db: Session,
    *,
    tenant_id: str,
    label: str,
    source_type: str,
    amount_cents: int,
    pay_day: int,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Insert a new active income line. Validates label / amount / pay_day
    at the service boundary so routes don't repeat the rules."""

    clean_label = (label or "").strip()
    if not clean_label:
        raise AppError("invalid_request", "请填写收入名称。", status_code=422)
    if len(clean_label) > _LABEL_MAX_LEN:
        raise AppError(
            "invalid_request",
            f"收入名称最多 {_LABEL_MAX_LEN} 个字符。",
            status_code=422,
        )
    clean_source = (source_type or "salary").strip()[:_SOURCE_TYPE_MAX_LEN]
    if amount_cents < 0:
        raise AppError(
            "invalid_request", "金额不能为负数。", status_code=422
        )
    if not 1 <= pay_day <= 31:
        raise AppError(
            "invalid_request", "发薪日需在 1 到 31 之间。", status_code=422
        )

    when = now or now_utc()
    row = MonthlyIncomePlan(
        tenant_id=tenant_id,
        label=clean_label,
        source_type=clean_source,
        amount_cents=amount_cents,
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
    label: str | None = None,
    source_type: str | None = None,
    amount_cents: int | None = None,
    pay_day: int | None = None,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Partial update. Only fields explicitly provided are changed.
    Archived plans cannot be edited — caller must reactivate first."""

    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    if plan.status == "archived":
        raise AppError(
            "state_conflict",
            "已归档的收入计划不能直接修改，请先恢复。",
            status_code=409,
        )

    if label is not None:
        clean = label.strip()
        if not clean:
            raise AppError("invalid_request", "请填写收入名称。", status_code=422)
        if len(clean) > _LABEL_MAX_LEN:
            raise AppError(
                "invalid_request",
                f"收入名称最多 {_LABEL_MAX_LEN} 个字符。",
                status_code=422,
            )
        plan.label = clean
    if source_type is not None:
        plan.source_type = source_type.strip()[:_SOURCE_TYPE_MAX_LEN] or "salary"
    if amount_cents is not None:
        if amount_cents < 0:
            raise AppError("invalid_request", "金额不能为负数。", status_code=422)
        plan.amount_cents = amount_cents
    if pay_day is not None:
        if not 1 <= pay_day <= 31:
            raise AppError(
                "invalid_request", "发薪日需在 1 到 31 之间。", status_code=422
            )
        plan.pay_day = pay_day

    plan.updated_at = now or now_utc()
    db.commit()
    db.refresh(plan)
    return plan


def archive_income_plan(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Soft-delete: status → archived, archived_at set. Idempotent."""

    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    if plan.status == "archived":
        return plan
    when = now or now_utc()
    plan.status = "archived"
    plan.archived_at = when
    plan.updated_at = when
    db.commit()
    db.refresh(plan)
    return plan


def restore_income_plan(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    now: datetime | None = None,
) -> MonthlyIncomePlan:
    """Reactivate an archived plan. Idempotent on already-active plans."""

    plan = _require_plan(db, tenant_id=tenant_id, public_id=public_id)
    if plan.status == "active":
        return plan
    when = now or now_utc()
    plan.status = "active"
    plan.archived_at = None
    plan.updated_at = when
    db.commit()
    db.refresh(plan)
    return plan


def total_monthly_income_cents(db: Session, *, tenant_id: str) -> int:
    """Sum of active income lines for the tenant. Drives the income leg
    of the v1.1 "本月可自由支配" formula in ``budget_baseline_service``."""

    total = db.scalar(
        add_ledger_scope(
            select(func.coalesce(func.sum(MonthlyIncomePlan.amount_cents), 0)),
            MonthlyIncomePlan,
            tenant_id,
        ).where(MonthlyIncomePlan.status == "active")
    )
    return int(total or 0)


def _require_plan(
    db: Session, *, tenant_id: str, public_id: str
) -> MonthlyIncomePlan:
    plan = db.scalar(
        select(MonthlyIncomePlan)
        .where(ledger_filter(MonthlyIncomePlan, tenant_id))
        .where(MonthlyIncomePlan.public_id == public_id)
        .limit(1)
    )
    if plan is None:
        raise AppError("not_found", "收入计划不存在。", status_code=404)
    return plan


__all__ = [
    "IncomeStatus",
    "archive_income_plan",
    "create_income_plan",
    "list_income_plans",
    "restore_income_plan",
    "total_monthly_income_cents",
    "update_income_plan",
]
