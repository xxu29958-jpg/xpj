"""Freeze repayment time with the existing calendar kernel, inside its command."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.schemas._debts import RepaymentCalendarResponse
from app.services.accounting_time_service import resolve_accounting_time
from app.services.ledger_calendar_service import calendar_revision, current_calendar


def repayment_calendar(db: Session, *, ledger_id: str) -> RepaymentCalendarResponse | None:
    rule = current_calendar(db, ledger_id=ledger_id)
    return RepaymentCalendarResponse(revision=rule.revision, timezone_name=rule.timezone_name) if rule else None


def resolve_repayment_time(
    db: Session, *, ledger_id: str, time_input: AccountingTimeInput | None, paid_at: datetime | None,
) -> AccountingTimeSnapshot | None:
    if paid_at is not None and paid_at.utcoffset() is None:
        raise AppError("accounting_time_invalid", "还款时刻需要明确的 UTC 偏移。", status_code=422)
    if time_input is None:
        return None  # Legacy input does not establish its precision or original calendar.
    if paid_at is not None and (paid_at.utcoffset() is None or paid_at != time_input.instant_utc):
        raise AppError("accounting_time_invalid", "还款时刻与原日期输入不一致，请核对。", status_code=422)
    rule = calendar_revision(db, ledger_id=ledger_id, revision=time_input.calendar_revision)
    if rule is None:
        raise AppError("calendar_revision_conflict", "未找到原还款任务的账务日历，请核对原输入。", status_code=409)
    return resolve_accounting_time(time_input, ledger_timezone=rule.timezone_name, calendar_revision=rule.revision)


def capture_repayment_time(db: Session, *, ledger_id: str, captured_at: datetime) -> AccountingTimeSnapshot:
    """Keep a notification's original instant and calendar before delayed review."""
    if captured_at.utcoffset() is None:
        raise AppError("accounting_time_invalid", "采集时刻需要明确的 UTC 偏移。", status_code=422)
    rule = current_calendar(db, ledger_id=ledger_id)
    if rule is None:
        raise AppError("calendar_revision_conflict", "未找到采集任务的账务日历。", status_code=409)
    return resolve_accounting_time(AccountingTimeInput(
        precision="instant", calendar_revision=rule.revision, user_local_date=captured_at.date(),
        instant_utc=captured_at, source_utc_offset_seconds=int(captured_at.utcoffset().total_seconds()),
    ), ledger_timezone=rule.timezone_name, calendar_revision=rule.revision)
