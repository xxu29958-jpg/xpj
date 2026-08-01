"""Exact money-cell parsing for the CSV import boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.errors import AppError
from app.money_contract import (
    MONEY_MINOR_MAX,
    MoneySign,
    parse_canonical_money_minor,
)
from app.services.currency_common import major_amount_to_minor, minor_amount_value
from app.services.exchange_rate_service import (
    BASE_CURRENCY_CODE,
    format_decimal_rate,
    normalize_currency_code,
)

_LEGACY_AMOUNT_YUAN_CURRENCY = "CNY"


@dataclass(frozen=True)
class CsvAmountParse:
    value: int | None
    display: str
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class CsvOptionalMinorParse:
    value: int | None
    error_code: str | None = None
    error_message: str | None = None


def legacy_yuan_value_from_minor(amount_minor: int) -> str:
    """Render the released ``amount_yuan`` compatibility value.

    This is deliberately CNY-two-fraction formatting, independent of the
    installation home currency.  New exports must also carry an explicit
    currency-aware home-major value; this helper exists only so the legacy
    column keeps its published meaning during the compatibility window.
    """

    return str(
        (Decimal(amount_minor) / Decimal(100)).quantize(Decimal("0.01"))
    )


def _parse_nonnegative_minor(
    raw: str,
    *,
    label: str,
) -> CsvOptionalMinorParse:
    if raw == "":
        return CsvOptionalMinorParse(None)
    try:
        value = parse_canonical_money_minor(
            raw,
            sign=MoneySign.NONNEGATIVE,
            label=f"csv.{label}",
        )
    except AppError:
        is_numeric_overflow = (
            raw.isascii()
            and raw.isdecimal()
            and len(raw) <= 32
            and int(raw, 10) > MONEY_MINOR_MAX
        )
        return CsvOptionalMinorParse(
            None,
            (
                "amount_out_of_range"
                if is_numeric_overflow
                else "amount_invalid"
            ),
            (
                f"{label} 超出当前版本可支持范围"
                if is_numeric_overflow
                else f"{label} 必须是无空白、无前导符号或前导零的十进制整数"
            ),
        )
    return CsvOptionalMinorParse(value)


def parse_legacy_amount(
    raw_yuan: str,
    raw_cents: str,
) -> CsvAmountParse:
    """Parse the released ``amount_yuan``/``amount_cents`` CSV contract.

    ``amount_yuan`` is the explicit compatibility header for the historical
    CNY two-fraction format.  It never consults the installation home currency.
    """

    parsed_yuan_cents: int | None = None
    if raw_yuan != "":
        try:
            parsed_yuan_cents = major_amount_to_minor(
                raw_yuan,
                _LEGACY_AMOUNT_YUAN_CURRENCY,
            )
        except AppError:
            return CsvAmountParse(
                None,
                raw_yuan,
                "amount_invalid",
                "amount_yuan 不是规范金额或超出当前版本可支持范围",
            )

    parsed_cents = _parse_nonnegative_minor(
        raw_cents,
        label="amount_cents",
    )
    if parsed_cents.error_message is not None:
        return CsvAmountParse(
            None,
            raw_cents,
            parsed_cents.error_code,
            parsed_cents.error_message,
        )
    if parsed_cents.value is not None:
        if (
            parsed_yuan_cents is not None
            and parsed_yuan_cents != parsed_cents.value
        ):
            return CsvAmountParse(
                None,
                raw_cents,
                "amount_mismatch",
                "amount_yuan 与 amount_cents 不一致",
            )
        return CsvAmountParse(
            parsed_cents.value,
            legacy_yuan_value_from_minor(parsed_cents.value),
        )
    if raw_yuan == "":
        return CsvAmountParse(
            None,
            "",
            "amount_missing",
            "缺少 amount_yuan 或 amount_cents",
        )
    assert parsed_yuan_cents is not None
    return CsvAmountParse(
        parsed_yuan_cents,
        legacy_yuan_value_from_minor(parsed_yuan_cents),
    )


def parse_optional_minor(
    raw: str,
    *,
    label: str,
) -> CsvOptionalMinorParse:
    return _parse_nonnegative_minor(raw, label=label)



def validate_csv_headers(headers: list[str]) -> None:
    """Reject ambiguous headers before row values can overwrite each other."""

    duplicates = sorted(
        header
        for header in set(headers)
        if header and headers.count(header) > 1
    )
    if duplicates:
        raise AppError(
            "invalid_request",
            f"CSV 表头重复：{', '.join(duplicates)}。",
            status_code=400,
        )
    if not any(
        header in {"amount_yuan", "amount_cents", "amount_home_major"}
        for header in headers
    ):
        raise AppError(
            "invalid_request",
            "CSV 必须包含 amount_yuan、amount_cents 或 amount_home_major 列。",
            status_code=400,
        )


def _parse_explicit_amount(
    *,
    raw_yuan: str,
    raw_cents: str,
    raw_home_major: str,
    declared_home: str,
) -> tuple[int | None, str, str | None, str | None]:
    parsed_minor = parse_optional_minor(raw_cents, label="amount_cents")
    if parsed_minor.error_message is not None:
        return (
            None,
            raw_cents,
            parsed_minor.error_code,
            parsed_minor.error_message,
        )
    parsed_major_minor: int | None = None
    if raw_home_major:
        try:
            parsed_major_minor = major_amount_to_minor(
                raw_home_major,
                declared_home,
            )
        except AppError:
            return (
                None,
                raw_home_major,
                "amount_invalid",
                "amount_home_major 不是该币种可精确表示的规范金额",
            )
    parsed_yuan_minor: int | None = None
    if raw_yuan:
        legacy = parse_legacy_amount(raw_yuan, "")
        if legacy.error_message is not None:
            return (
                None,
                raw_yuan,
                legacy.error_code,
                legacy.error_message,
            )
        parsed_yuan_minor = legacy.value
    candidates = tuple(
        value
        for value in (
            parsed_minor.value,
            parsed_major_minor,
            parsed_yuan_minor,
        )
        if value is not None
    )
    if not candidates:
        return (
            None,
            "",
            "amount_missing",
            "缺少可验证的 home-currency 金额",
        )
    if len(set(candidates)) != 1:
        return (
            None,
            raw_cents or raw_home_major or raw_yuan,
            "amount_mismatch",
            "amount_cents、amount_home_major 与 amount_yuan 不一致",
        )
    value = candidates[0]
    return value, minor_amount_value(value, declared_home), None, None


def _parse_amount(
    cells: dict[str, str],
    *,
    home_currency: str,
) -> tuple[int | None, str, str | None, str | None]:
    """Parse legacy CNY or an explicitly bound home-currency amount."""

    raw_yuan = cells.get("amount_yuan", "")
    raw_cents = cells.get("amount_cents", "")
    raw_home_major = cells.get("amount_home_major", "")
    declared_raw = cells.get("home_currency_code", "").strip()
    if not declared_raw:
        if home_currency != BASE_CURRENCY_CODE or raw_home_major:
            return (
                None,
                raw_home_major or raw_cents or raw_yuan,
                "client_upgrade_required",
                "当前账本不是 CNY，旧 CSV 缺少明确的 home_currency_code；请使用新版导出重新导入",
            )
        parsed = parse_legacy_amount(raw_yuan, raw_cents)
        return parsed.value, parsed.display, parsed.error_code, parsed.error_message
    try:
        declared_home = normalize_currency_code(declared_raw)
    except AppError:
        return None, declared_raw, "currency_not_supported", "home_currency_code 暂不支持"
    if declared_home != home_currency:
        return (
            None,
            declared_home,
            "client_upgrade_required",
            f"CSV home_currency_code={declared_home} 与当前账本 {home_currency} 不一致；禁止跨本位币静默导入",
        )
    if raw_yuan and declared_home != BASE_CURRENCY_CODE:
        return (
            None,
            raw_yuan,
            "client_upgrade_required",
            "amount_yuan 只表示 CNY；非 CNY 文件必须使用新版金额列",
        )
    return _parse_explicit_amount(
        raw_yuan=raw_yuan,
        raw_cents=raw_cents,
        raw_home_major=raw_home_major,
        declared_home=declared_home,
    )


def _parse_optional_int(
    raw: str,
    label: str,
) -> tuple[int | None, str | None, str | None]:
    parsed = parse_optional_minor(raw, label=label)
    return parsed.value, parsed.error_code, parsed.error_message


def _parse_optional_decimal(raw: str, label: str) -> tuple[Decimal | None, str | None]:
    if raw == "":
        return None, None
    try:
        from app.money_carrier import parse_canonical_major_decimal

        return format_decimal_rate(
            parse_canonical_major_decimal(raw)
        ), None
    except (ValueError, AppError):
        return None, f"{label} 不是合法数字"

__all__ = [
    "CsvAmountParse",
    "CsvOptionalMinorParse",
    "legacy_yuan_value_from_minor",
    "parse_legacy_amount",
    "parse_optional_minor",
]
