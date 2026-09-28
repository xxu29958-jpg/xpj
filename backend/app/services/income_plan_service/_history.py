"""Month interpretation and immutable publication for the IncomePlan owner."""

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.schemas._income_history import IncomePlanDefinition, IncomePlanHistoryResponse, IncomePlanRevisionResponse
from app.services.spending_contract_service import accounting_zone, parse_month
from app.services.time_service import ensure_utc


def income_month_start(value: str | None) -> date:
    return date(*parse_month(value), 1)


def income_intent_month(value: str | None, when: datetime) -> date:
    current = ensure_utc(when).astimezone(accounting_zone()).date().replace(day=1)
    period = income_month_start(value) if value is not None else current
    if period > current:
        raise AppError("invalid_request", "暂不支持预先安排未来月份的计划变更。", status_code=422)
    return period


def income_change_month(
    *, current_frequency: str | None, current_income_month: str | None,
    frequency: str, income_month: str | None, period: date,
) -> date:
    if frequency != "one_time":
        return period
    target = income_month_start(income_month)
    if current_frequency == "monthly" and target < period:
        raise AppError("invalid_request", "改为单次计划时，目标月份不能早于本次生效月份。", status_code=422)
    if current_frequency == "one_time":
        return min(period, target, income_month_start(current_income_month))
    return min(period, target)


def require_forward_income_month(db: Session, plan: MonthlyIncomePlan, period: date) -> None:
    latest = db.scalar(select(func.max(IncomePlanRevision.intent_month)).where(
        IncomePlanRevision.tenant_id == plan.tenant_id, IncomePlanRevision.plan_id == plan.id,
    ))
    if latest is not None and period < latest:
        raise AppError("state_conflict", "计划已有更晚月份的变更，请核对当前计划后重新提交。", status_code=409)


def require_income_status_month(db: Session, plan: MonthlyIncomePlan, period: date) -> None:
    """An existing status completes only the month represented by its latest head."""
    latest = db.scalar(select(IncomePlanRevision).where(
        IncomePlanRevision.tenant_id == plan.tenant_id, IncomePlanRevision.plan_id == plan.id,
    ).order_by(IncomePlanRevision.revision_number.desc()).limit(1))
    if (
        latest is None
        or latest.revision_number != plan.row_version
        or latest.status != plan.status
        or latest.intent_month != period
    ):
        raise AppError("state_conflict", "请核对当前计划的生效月份后重新提交。", status_code=409)


def append_income_revision(
    db: Session, plan: MonthlyIncomePlan, *, period: date, intent_period: date, change_kind: str,
    actor_account_id: int | None, when: datetime,
) -> None:
    db.add(IncomePlanRevision(
        tenant_id=plan.tenant_id, plan_id=plan.id, revision_number=plan.row_version,
        effective_month=period, intent_month=intent_period, change_kind=change_kind, label=plan.label,
        source_type=plan.source_type, frequency=plan.frequency, income_month=plan.income_month,
        home_currency_code=plan.home_currency_code, amount_cents=plan.amount_cents,
        pay_day=plan.pay_day, status=plan.status,
        actor_account_id=actor_account_id, recorded_at=when,
    ))
    db.flush()


def income_plan_history(db: Session, *, tenant_id: str, public_id: str,
    before_version: int | None = None, limit: int = 20) -> IncomePlanHistoryResponse:
    plan = db.scalar(ledger_scoped_select(MonthlyIncomePlan, tenant_id).where(MonthlyIncomePlan.public_id == public_id))
    if plan is None:
        raise AppError("income_plan_not_found", status_code=404)
    query = select(IncomePlanRevision).where(IncomePlanRevision.tenant_id == tenant_id, IncomePlanRevision.plan_id == plan.id)
    if before_version is not None:
        query = query.where(IncomePlanRevision.revision_number < before_version)
    rows = db.scalars(query.order_by(IncomePlanRevision.revision_number.desc()).limit(limit + 1)).all()
    selected = rows[:limit]
    return IncomePlanHistoryResponse(ledger_id=tenant_id, public_id=public_id,
        items=[IncomePlanRevisionResponse(row_version=row.revision_number, change_kind=row.change_kind,
            recorded_at=row.recorded_at, intent_month=row.intent_month.strftime("%Y-%m") if row.intent_month else None,
            effective_month=row.effective_month.strftime("%Y-%m") if row.effective_month else None,
            snapshot=IncomePlanDefinition.model_validate(row)) for row in selected],
        next_before_version=selected[-1].revision_number if len(rows) > limit else None)
