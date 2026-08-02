"""Shared parsing and HTTP-status rules for Web expense forms."""

from __future__ import annotations

from datetime import datetime

from app.errors import AppError
from app.money_carrier import parse_canonical_major_decimal
from app.services.currency_common import currency_input_metadata, major_amount_to_minor
from app.services.spending_contract_service import accounting_timezone_key
from app.services.time_service import ensure_utc_assuming_local


def web_form_error_status(exc: AppError) -> int:
    """Keep protocol conflicts while mapping rejected form commands to 422."""

    return 422 if exc.status_code in {400, 422} else exc.status_code


def parse_amount_yuan(
    raw: str,
    *,
    currency_code: str,
) -> tuple[int | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    try:
        amount = major_amount_to_minor(
            text,
            currency_code,
            allow_negative=True,
        )
    except AppError:
        example = currency_input_metadata(currency_code)["amount_example"]
        return None, f"请填写正确的金额，例如 {example}。"
    if amount is not None and amount < 0:
        return None, "金额不能为负数。"
    return amount, None


def parse_original_amount_minor(
    raw: str,
    *,
    currency_code: str,
) -> tuple[int | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    try:
        amount = parse_canonical_major_decimal(text, allow_negative=True)
    except ValueError:
        metadata = currency_input_metadata(currency_code)
        return None, f"请填写正确的金额，例如 {metadata['amount_example']}。"
    if amount < 0:
        return None, "金额不能为负数。"
    try:
        amount_minor = major_amount_to_minor(
            amount,
            currency_code,
            allow_negative=True,
        )
    except AppError:
        metadata = currency_input_metadata(currency_code)
        if metadata["minor_unit_digits"] == 0:
            return None, f"{currency_code.upper()} 只支持整数金额。"
        return None, "金额格式不正确。"
    return amount_minor, None


def parse_expense_time_local(raw: str | None) -> tuple[datetime | None, str | None]:
    """Parse a datetime-local wall clock in the configured accounting zone."""

    cleaned = (raw or "").strip()
    if not cleaned:
        return None, None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None, "请填写正确的时间。"
    return ensure_utc_assuming_local(parsed, accounting_timezone_key()), None
