"""Currency-aware amount, time, and expense view models for ``/web``."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import CURRENCY_SYMBOLS, FX_STATUS_PENDING, NO_FRACTION_CURRENCY_CODES
from app.money_contract import projection_sum_to_int
from app.services import bill_split_service, web_stats_service
from app.services.currency_common import (
    currency_input_metadata,
    minor_amount_label,
    minor_amount_value,
)
from app.services.data_quality_service import (
    is_uncategorized_expense_category,
    is_usable_pending_merchant,
)
from app.services.spending_contract_service import (
    accounting_datetime_label,
    accounting_zone,
    stat_time,
)
from app.services.time_service import ensure_utc, parse_month_label
from app.services.time_service import to_iso as _datetime_to_iso


def _amount_yuan(amount_cents: int | None, currency_code: str) -> str:
    """Legacy view-model key backed by the currency-aware minor formatter."""

    return minor_amount_value(amount_cents, currency_code)


def _month_display_label(value: str | None, *, fallback: str = "所选月份") -> str:
    parsed = parse_month_label(value)
    if parsed is None:
        return fallback
    year, month = parsed
    return f"{year} 年 {month} 月"


def _calendar_date_label(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        normalized = ensure_utc(value)
        if normalized is None:
            return ""
        calendar_date = normalized.astimezone(accounting_zone()).date()
    else:
        calendar_date = value
    return f"{calendar_date.year} 年 {calendar_date.month} 月 {calendar_date.day} 日"


def _expense_time_local_input(value) -> str:
    return accounting_datetime_label(value, pattern="%Y-%m-%dT%H:%M")


def _currency_symbol(currency_code: str) -> str:
    code = currency_code.upper()
    return CURRENCY_SYMBOLS.get(code, f"{code} ")


def _minor_amount_label(
    amount_minor: int | None,
    currency_code: str | None,
) -> str:
    return minor_amount_label(amount_minor, currency_code)


def _minor_amount_value(
    amount_minor: int | None,
    currency_code: str | None,
) -> str:
    return minor_amount_value(amount_minor, currency_code)


def _home_amount_label(amount_cents: int | None, currency_code: str) -> str:
    return _minor_amount_label(amount_cents, currency_code)


def _currency_input_view(currency_code: str) -> dict[str, object]:
    return currency_input_metadata(currency_code)


def _required_currency_code(*candidates: str | None) -> str:
    for candidate in candidates:
        if candidate:
            return candidate.upper()
    raise AppError("currency_binding_corrupt", status_code=503)


def _amount_segments(
    amount_cents: int | None,
    currency_code: str | None = None,
) -> dict[str, str]:
    """Split a display amount into currency, integer, and fraction segments."""

    code = _required_currency_code(currency_code)
    symbol = _currency_symbol(code)
    cents = projection_sum_to_int(
        amount_cents,
        label="web.amount_segments",
        empty_is_zero=True,
    )
    if code in NO_FRACTION_CURRENCY_CODES:
        return {"cur": symbol, "int": f"{cents:,}", "dec": ""}
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return {"cur": symbol, "int": f"{sign}{whole:,}", "dec": f".{frac:02d}"}


def _expense_amount_labels(
    expense,
    *,
    presentation_currency_code: str | None = None,
) -> tuple[str, str | None]:
    home_code = _required_currency_code(
        getattr(expense, "home_currency_code", None),
        presentation_currency_code,
    )
    original_code = (getattr(expense, "original_currency_code", None) or home_code).upper()
    original_minor = getattr(expense, "original_amount_minor", None)
    amount_cents = getattr(expense, "amount_cents", None)
    is_foreign = original_code != home_code
    primary = (
        _minor_amount_label(original_minor, original_code)
        if is_foreign and original_minor is not None
        else _home_amount_label(amount_cents, home_code)
    )
    if not is_foreign:
        return primary, None
    rate_date = getattr(expense, "exchange_rate_date", None)
    date_text = rate_date.isoformat() if hasattr(rate_date, "isoformat") else (str(rate_date) if rate_date else "")
    if getattr(expense, "fx_status", "") == FX_STATUS_PENDING or amount_cents is None:
        return primary, f"汇率待同步{(' · ' + date_text) if date_text else ''}"
    rate = getattr(expense, "exchange_rate_to_cny", None)
    if rate is None:
        return primary, f"汇率待同步{(' · ' + date_text) if date_text else ''}"
    meta = f"≈ {_home_amount_label(amount_cents, home_code)} · 汇率 1 {original_code} = {rate} {home_code}"
    if date_text:
        meta += f" · {date_text}"
    return primary, meta


def _trend14_amounts(
    db: Session,
    ledger_id: str,
    *,
    currency_code: str,
) -> list[dict]:
    return web_stats_service.trend14_amounts(
        db,
        ledger_id,
        currency_code=currency_code,
    )


def _confirmed_by_day(
    db: Session,
    ledger_id: str,
    month: str,
    *,
    currency_code: str,
    tag: str | None = None,
) -> list[dict]:
    return web_stats_service.confirmed_by_day(
        db,
        ledger_id,
        month,
        currency_code=currency_code,
        tag=tag,
    )


def _confirmed_source_breakdown(
    db: Session,
    ledger_id: str,
    month: str | None,
    *,
    tag: str | None = None,
) -> list[dict]:
    return web_stats_service.source_breakdown(db, ledger_id, month, tag=tag)


def _expense_view(
    expense,
    *,
    presentation_currency_code: str | None = None,
) -> dict:
    amount_label, fx_meta = _expense_amount_labels(
        expense,
        presentation_currency_code=presentation_currency_code,
    )
    home_code = _required_currency_code(
        getattr(expense, "home_currency_code", None),
        presentation_currency_code,
    )
    original_code = getattr(expense, "original_currency_code", None) or home_code
    original_minor = getattr(expense, "original_amount_minor", None)
    has_image = bool(expense.image_path) and not expense.image_deleted_at
    if has_image:
        image_state = "available"
    elif expense.image_deleted_at is not None:
        image_state = "cleaned"
    else:
        image_state = "missing"
    source_raw = getattr(expense, "source", "") or ""
    source_label = web_stats_service.source_label(source_raw, "未知")
    is_split_received = source_raw == bill_split_service.SPLIT_RECEIVED_SOURCE
    needs_amount = expense.amount_cents is None
    needs_merchant = not is_usable_pending_merchant(expense.merchant)
    needs_category = is_uncategorized_expense_category(expense.category)
    is_duplicate = (getattr(expense, "duplicate_status", None) or "") == "suspected"
    return {
        "id": expense.id,
        "amount_yuan": _amount_yuan(expense.amount_cents, home_code),
        "amount_cents": expense.amount_cents,
        "home_currency_code": home_code,
        "original_currency_code": original_code,
        "original_amount_minor": original_minor,
        "original_amount_value": _minor_amount_value(original_minor, original_code)
        or _amount_yuan(expense.amount_cents, home_code),
        "amount_symbol": _currency_symbol(original_code),
        "is_foreign_currency": original_code != home_code,
        "exchange_rate_to_cny": getattr(expense, "exchange_rate_to_cny", None),
        "exchange_rate_date": getattr(expense, "exchange_rate_date", None),
        "exchange_rate_source": getattr(expense, "exchange_rate_source", None),
        "fx_status": getattr(expense, "fx_status", ""),
        "amount_label": amount_label,
        "fx_meta": fx_meta,
        "merchant": expense.merchant or "",
        "category": expense.category or "未分类",
        # Display labels and legacy dirty tokens are not writable facts. Forms
        # render every semantic-uncategorized value as blank so unrelated edits
        # neither persist a display label nor normalize history to "其他".
        "category_input": "" if needs_category else expense.category,
        "note": expense.note or "",
        "tags": getattr(expense, "tags", None) or "",
        "value_score": getattr(expense, "value_score", None),
        "regret_score": getattr(expense, "regret_score", None),
        "status": expense.status,
        "expense_time": accounting_datetime_label(expense.expense_time),
        "stat_time": accounting_datetime_label(stat_time(expense)),
        "expense_time_local": _expense_time_local_input(getattr(expense, "expense_time", None)),
        "updated_at_iso": _datetime_to_iso(getattr(expense, "updated_at", None)),
        "row_version": getattr(expense, "row_version", None),
        "created_at": accounting_datetime_label(expense.created_at),
        "has_image": has_image,
        "image_state": image_state,
        "duplicate_status": expense.duplicate_status,
        "is_duplicate": is_duplicate,
        "needs_amount": needs_amount,
        "needs_merchant": needs_merchant,
        "needs_category": needs_category,
        "fx_pending": getattr(expense, "fx_status", "") == FX_STATUS_PENDING,
        "source_label": source_label,
        "is_split_received": is_split_received,
    }
