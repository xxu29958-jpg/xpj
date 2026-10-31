"""Pure time-component projection shared by saved choices and miss diagnostics."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import Expense
from app.services.accounting_time_service import accounting_time_snapshot


def time_components(expense: Expense) -> dict:
    snapshot = accounting_time_snapshot(expense)
    if snapshot is None:
        return {}
    value = expense.user_local_date
    if expense.time_precision == "instant" and expense.expense_time is not None:
        zone = (timezone(timedelta(seconds=expense.source_utc_offset_seconds))
            if expense.source_utc_offset_seconds is not None else ZoneInfo(expense.source_timezone)
            if expense.source_timezone else None)
        if zone is not None:
            value = expense.expense_time.astimezone(zone)
    if value is None:
        return {}
    return {"year": value.year, "month": value.month, "day": value.day,
        **({"hour": value.hour, "minute": value.minute, "second": value.second} if isinstance(value, datetime) else {}),
        "timezone": expense.source_timezone, "offset_seconds": expense.source_utc_offset_seconds,
        "precision": expense.time_precision}


def candidate_components(candidate) -> dict:
    if candidate.requires_year:
        return {"year": None, **candidate.components, "timezone": candidate.source_timezone,
            **({"offset_seconds": candidate.source_utc_offset_seconds} if candidate.source_utc_offset_seconds is not None else {}),
            "precision": "date_only" if candidate.precision == "date_only" else "instant"}
    try:
        value = datetime.fromisoformat(candidate.local_value)
    except ValueError:
        return {}
    return {"year": value.year, "month": value.month, "day": value.day,
        **({"hour": value.hour, "minute": value.minute, "second": value.second}
           if candidate.precision != "date_only" else {}),
        "timezone": candidate.source_timezone, "offset_seconds": candidate.source_utc_offset_seconds,
        "precision": "date_only" if candidate.precision == "date_only" else "instant"}
