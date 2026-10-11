"""Original principal occurrence evidence; recording time is a separate fact."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.services.accounting_time_service import resolve_accounting_time
from app.services.ledger_calendar_service import calendar_revision, current_calendar
from app.services.time_service import strict_zone


def resolve_principal_time(
    db: Session, *, ledger_id: str, time_input: AccountingTimeInput | None, event_time: datetime | None,
) -> AccountingTimeSnapshot | None:
    if event_time is not None and event_time.utcoffset() is None:
        raise AppError("accounting_time_invalid", "本金发生时刻需要明确的 UTC 偏移。", status_code=422)
    if time_input is None:
        # Old form adapters may have manufactured midnight from a date. Keep the
        # received timestamp but do not invent precision, source date or calendar.
        return AccountingTimeSnapshot(instant_utc=event_time, basis="legacy_unknown") if event_time else None
    if event_time is not None and event_time != time_input.instant_utc:
        raise AppError("accounting_time_invalid", "本金时刻与原日期输入不一致，请核对。", status_code=422)
    rule = calendar_revision(db, ledger_id=ledger_id, revision=time_input.calendar_revision)
    if rule is None:
        raise AppError("calendar_revision_conflict", "未找到原往来任务的账务日历，请核对原输入。", status_code=409)
    return resolve_accounting_time(time_input, ledger_timezone=rule.timezone_name, calendar_revision=rule.revision)


def agreement_principal_time(db: Session, *, ledger_id: str, accepted_at: datetime) -> AccountingTimeSnapshot:
    """A return obligation starts when the other party accepts the new agreement."""
    rule = current_calendar(db, ledger_id=ledger_id)
    if rule is None:
        raise AppError("calendar_revision_conflict", "未找到新约定的账务日历。", status_code=409)
    local = accepted_at.astimezone(strict_zone(rule.timezone_name))
    return resolve_accounting_time(AccountingTimeInput(precision="instant", calendar_revision=rule.revision,
        user_local_date=local.date(), instant_utc=accepted_at, source_timezone=rule.timezone_name,
        source_utc_offset_seconds=int(local.utcoffset().total_seconds())),
        ledger_timezone=rule.timezone_name, calendar_revision=rule.revision)
