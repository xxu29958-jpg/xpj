"""One revision projection for whole-month and scheduled-to-date estimates."""

from calendar import monthrange
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import IncomePlanRevision
from app.money_contract import projection_sum_to_int
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code
from app.services.money_projection_service import ProjectionGap, project_recorded_amount


@dataclass(frozen=True)
class IncomeForecast:
    projected_entries: tuple[tuple[IncomePlanRevision, int | None], ...]
    home_currency_code: str
    expected_amount_cents: int | None
    scheduled_amount_cents: int | None
    missing_currency_codes: tuple[str, ...]

    @property
    def entries(self) -> tuple[IncomePlanRevision, ...]:
        return tuple(row for row, _ in self.projected_entries)


def _applicable_revisions(revisions: Iterable[IncomePlanRevision], period: date) -> list[IncomePlanRevision]:
    chosen: dict[int, IncomePlanRevision] = {}
    preceding: dict[int, IncomePlanRevision] = {}
    month = period.strftime("%Y-%m")
    for revision in sorted(revisions, key=lambda row: row.revision_number):
        previous = preceding.get(revision.plan_id)
        preceding[revision.plan_id] = revision
        applies = revision.effective_month is None or revision.effective_month <= period
        if previous is not None and revision.change_kind == "edit" and (
            previous.frequency == revision.frequency == "one_time"
        ):
            # A single-month correction changes its old/new targets, not an
            # unrelated monthly schedule that preceded the conversion.
            assert revision.intent_month is not None  # Typed revision constraint excludes undated edits.
            selected = chosen.get(revision.plan_id)
            history_known = selected is not None and selected.effective_month is not None
            financial_correction = (
                previous.income_month, previous.amount_cents, previous.pay_day, previous.home_currency_code,
            ) != (revision.income_month, revision.amount_cents, revision.pay_day, revision.home_currency_code)
            # A rename or source label does not establish an undated baseline's
            # historical amount. Keep that marker through consecutive metadata
            # edits; actual financial corrections can still declare old/new targets.
            applies = period >= revision.intent_month or (
                month in {previous.income_month, revision.income_month}
                and (history_known or financial_correction)
            )
        if applies:
            chosen[revision.plan_id] = revision
    return list(chosen.values())


def _project_revision_amount(row: IncomePlanRevision, home: str, project_amount) -> int | None:
    if row.home_currency_code is None:
        return None
    if row.home_currency_code == home:
        return row.amount_cents
    if project_amount is None:
        return None
    return project_amount(row.amount_cents, row.home_currency_code)


def forecast_from_revisions(
    revisions: Iterable[IncomePlanRevision], *, period: date, today: date, home_currency_code: str,
    project_amount: Callable[[int, str], int | None] | None = None,
) -> IncomeForecast:
    home = normalize_currency_code(home_currency_code)
    chosen = _applicable_revisions(revisions, period)
    current = today.replace(day=1)
    if period < current and any(row.effective_month is None for row in chosen):
        raise AppError("invalid_request", "这个月份的历史计划尚未记录，无法重建收入预测。", status_code=422)
    month = period.strftime("%Y-%m")
    entries = tuple(row for row in chosen if row.status == "active" and (
        row.frequency == "monthly" or row.income_month == month
    ))
    last_day = monthrange(period.year, period.month)[1]
    projected = [(row, _project_revision_amount(row, home, project_amount)) for row in entries]
    due = [amount for row, amount in projected if period < current or (
        period == current and min(row.pay_day, last_day) <= today.day)]
    return IncomeForecast(
        projected_entries=tuple(projected),
        home_currency_code=home,
        expected_amount_cents=_sum_projection([amount for _, amount in projected], label="income_plan.expected"),
        scheduled_amount_cents=_sum_projection(due, label="income_plan.scheduled"),
        missing_currency_codes=tuple(sorted({row.home_currency_code or "UNKNOWN" for row, amount in projected if amount is None})),
    )


def _sum_projection(values: list[int | None], *, label: str) -> int | None:
    if any(value is None for value in values):
        return None
    return projection_sum_to_int(sum(value for value in values if value is not None), label=label)


def query_income_forecast(
    db: Session, *, tenant_id: str, period: date, today: date,
    home_currency_code: str | None = None, missing_rates: set[ProjectionGap] | None = None,
) -> IncomeForecast:
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    rate_date = min(today, period.replace(day=monthrange(period.year, period.month)[1]))
    revisions = db.scalars(select(IncomePlanRevision).where(
        IncomePlanRevision.tenant_id == tenant_id,
    ))
    forecast = forecast_from_revisions(
        revisions, period=period, today=today, home_currency_code=home,
        project_amount=lambda amount, code: project_recorded_amount(
            db, tenant_id=tenant_id, amount_minor=amount, source_currency=code, home_currency=home, rate_date=rate_date,
        ),
    )
    if missing_rates is not None:
        missing_rates.update(ProjectionGap(row.home_currency_code, home, rate_date)
            for row, amount in forecast.projected_entries if amount is None)
    return forecast
