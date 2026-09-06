"""One revision projection for whole-month and scheduled-to-date estimates."""

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import IncomePlanRevision
from app.money_contract import projection_sum_to_int


@dataclass(frozen=True)
class IncomeForecast:
    entries: tuple[IncomePlanRevision, ...]
    expected_amount_cents: int
    scheduled_amount_cents: int


def _applicable_revisions(revisions: Iterable[IncomePlanRevision], period: date) -> list[IncomePlanRevision]:
    chosen: dict[int, IncomePlanRevision] = {}
    for revision in revisions:
        if revision.effective_month is not None and revision.effective_month > period:
            continue
        previous = chosen.get(revision.plan_id)
        if previous is None or revision.revision_number > previous.revision_number:
            chosen[revision.plan_id] = revision
    return list(chosen.values())


def forecast_from_revisions(
    revisions: Iterable[IncomePlanRevision], *, period: date, today: date,
) -> IncomeForecast:
    chosen = _applicable_revisions(revisions, period)
    current = today.replace(day=1)
    if period < current and any(row.effective_month is None for row in chosen):
        raise AppError("invalid_request", "这个月份的历史计划尚未记录，无法重建收入预测。", status_code=422)
    month = period.strftime("%Y-%m")
    entries = tuple(row for row in chosen if row.status == "active" and (
        row.frequency == "monthly" or row.income_month == month
    ))
    last_day = monthrange(period.year, period.month)[1]
    due = (row for row in entries if period < current or (
        period == current and min(row.pay_day, last_day) <= today.day
    ))
    return IncomeForecast(
        entries=entries,
        expected_amount_cents=projection_sum_to_int(sum(row.amount_cents for row in entries), label="income_plan.expected"),
        scheduled_amount_cents=projection_sum_to_int(sum(row.amount_cents for row in due), label="income_plan.scheduled"),
    )


def query_income_forecast(db: Session, *, tenant_id: str, period: date, today: date) -> IncomeForecast:
    revisions = db.scalars(select(IncomePlanRevision).where(
        IncomePlanRevision.tenant_id == tenant_id,
        or_(IncomePlanRevision.effective_month.is_(None), IncomePlanRevision.effective_month <= period),
    ))
    return forecast_from_revisions(revisions, period=period, today=today)
