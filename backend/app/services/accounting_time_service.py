"""Pure financial-date interpretation using an explicitly resolved ledger rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.errors import AppError
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.services.time_service import ensure_utc, strict_zone

_EVIDENCE_FIELDS = {
    "accounting_date": "accounting_date",
    "calendar_revision": "calendar_revision",
    "user_local_date": "user_local_date",
    "precision": "time_precision",
    "source_timezone": "source_timezone",
    "source_utc_offset_seconds": "source_utc_offset_seconds",
    "basis": "accounting_date_basis",
}


def _calendar_zone(ledger_timezone: str, calendar_revision: int):
    if type(calendar_revision) is not int or calendar_revision <= 0:
        raise AppError("calendar_revision_conflict", "账务日历版本无效，请核对原输入。", status_code=409)
    return strict_zone(ledger_timezone)


def _instant_source(value: AccountingTimeInput) -> tuple[datetime, int]:
    instant = value.instant_utc.astimezone(UTC)
    if value.source_timezone is not None:
        local = instant.astimezone(strict_zone(value.source_timezone))
    elif value.source_utc_offset_seconds is not None:
        local = instant.astimezone(timezone(timedelta(seconds=value.source_utc_offset_seconds)))
    else:
        raise AppError("accounting_time_invalid", "请保留原输入的时区或 UTC 偏移。", status_code=422)
    offset = int(local.utcoffset().total_seconds())
    if local.date() != value.user_local_date:
        raise AppError("accounting_time_invalid", "输入日期与原时区中的时刻不一致。", status_code=422)
    if value.source_utc_offset_seconds is not None and value.source_utc_offset_seconds != offset:
        raise AppError("accounting_time_invalid", "输入偏移与该时刻的原时区不一致。", status_code=422)
    return instant, offset


def resolve_accounting_time(
    time_input: AccountingTimeInput, *, ledger_timezone: str, calendar_revision: int,
) -> AccountingTimeSnapshot:
    """Interpret once against the captured rule, which need not be the current one."""
    zone = _calendar_zone(ledger_timezone, calendar_revision)
    if time_input.calendar_revision != calendar_revision:
        raise AppError("calendar_revision_conflict", "未找到输入所用的账务日历版本，请核对原输入。", status_code=409)
    instant = offset = None
    day = time_input.user_local_date
    basis = "user_date"
    if time_input.precision == "instant":
        instant, offset = _instant_source(time_input)
        day, basis = instant.astimezone(zone).date(), "instant_calendar"
    elif time_input.source_timezone is not None:
        source = strict_zone(time_input.source_timezone)
        if source.key != zone.key and time_input.accounting_date is None:
            raise AppError("accounting_date_required", "不同地区的日期需要明确选择账务归属日。", status_code=422)
    if time_input.accounting_date is not None:
        day, basis = time_input.accounting_date, "user_selected"
    return AccountingTimeSnapshot(precision=time_input.precision, instant_utc=instant,
        user_local_date=time_input.user_local_date, source_timezone=time_input.source_timezone,
        source_utc_offset_seconds=offset, accounting_date=day, calendar_revision=calendar_revision, basis=basis)


def legacy_accounting_time(
    *, expense_time: datetime | None, confirmed_at: datetime | None = None,
    ledger_timezone: str, calendar_revision: int,
) -> AccountingTimeSnapshot:
    """Use the saved initial compatibility rule without inventing source precision."""
    zone = _calendar_zone(ledger_timezone, calendar_revision)
    instant = ensure_utc(expense_time)
    effective = instant or ensure_utc(confirmed_at)
    basis = "legacy_expense_time" if instant is not None else "legacy_confirmed_at"
    return AccountingTimeSnapshot(instant_utc=instant, calendar_revision=calendar_revision,
        accounting_date=effective.astimezone(zone).date() if effective is not None else None,
        basis=basis if effective is not None else "legacy_unknown")


def apply_accounting_time(expense: object, snapshot: AccountingTimeSnapshot) -> None:
    """Apply only time evidence; the existing financial writer owns OCC and commit."""
    for field, attribute in _EVIDENCE_FIELDS.items():
        setattr(expense, attribute, getattr(snapshot, field))
    expense.expense_time = snapshot.instant_utc


def accounting_time_snapshot(expense: object) -> AccountingTimeSnapshot | None:
    """Project saved evidence only; an old value does not acquire today's rule."""
    evidence = {field: getattr(expense, attribute, None) for field, attribute in _EVIDENCE_FIELDS.items()}
    if all(value is None for value in evidence.values()):
        return None
    evidence["precision"] = evidence["precision"] or "unknown"
    return AccountingTimeSnapshot(**evidence, instant_utc=getattr(expense, "expense_time", None))
