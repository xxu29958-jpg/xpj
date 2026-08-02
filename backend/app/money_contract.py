"""Money validation and the stable public money-contract facade."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import CheckConstraint

from app.errors import AppError
from app.money_contract_manifest import (
    GOAL_MONTH_SHAPE_CHECK_V1 as GOAL_MONTH_SHAPE_CHECK_V1,
)
from app.money_contract_manifest import (
    MONEY_COLUMNS_V1,
)
from app.money_contract_manifest import (
    MONEY_FINAL_CHECKS_V1 as MONEY_FINAL_CHECKS_V1,
)
from app.money_contract_manifest import (
    MONEY_REMOVED_LEGACY_CHECKS_V1 as MONEY_REMOVED_LEGACY_CHECKS_V1,
)
from app.money_contract_types import (
    MONEY_AGGREGATE_MAX,
    MONEY_MINOR_MAX,
    MoneyColumn,
    MoneySign,
    final_sign_bounds,
)
from app.money_contract_types import (
    MONEY_CONTRACT_PHASE_C07 as MONEY_CONTRACT_PHASE_C07,
)
from app.money_contract_types import (
    MONEY_CONTRACT_PHASE_KEY as MONEY_CONTRACT_PHASE_KEY,
)
from app.money_contract_types import (
    MoneyCheck as MoneyCheck,
)
from app.money_contract_types import (
    RemovedMoneyCheck as RemovedMoneyCheck,
)

logger = logging.getLogger(__name__)

_MAX_C07_INTEGER_TEXT_LENGTH = len(str(-MONEY_MINOR_MAX))


def is_canonical_money_minor_text(value: object) -> bool:
    """Return whether ``value`` is the exact base-10 integer wire form."""

    if type(value) is not str or not value or len(value) > _MAX_C07_INTEGER_TEXT_LENGTH:
        return False
    if value == "0":
        return True
    digits = value[1:] if value[0] == "-" else value
    return bool(digits) and digits[0] in "123456789" and digits.isascii() and digits.isdecimal()


def c07_entry_bounds(sign: MoneySign) -> tuple[int, int]:
    """ADR-0073 C07 command bounds for one submitted money fact."""

    return final_sign_bounds(sign)


def money_columns_for_table(table: str) -> tuple[MoneyColumn, ...]:
    return tuple(column for column in MONEY_COLUMNS_V1 if column.table == table)


def money_check_constraints_for_table(table: str) -> tuple[CheckConstraint, ...]:
    """Build the C07 permanent money bounds."""

    columns = money_columns_for_table(table)
    return tuple(CheckConstraint(check.predicate, name=check.name) for column in columns for check in column.checks)


def _coerce_input_int(value: object, *, label: str) -> int:
    """Accept only a real Python int for authoritative command input."""

    if type(value) is not int:
        raise TypeError(f"{label}: unsupported input carrier {type(value).__name__}")
    return value


def _coerce_database_integer(value: object, *, label: str) -> int | None:
    """Accept exact PostgreSQL integer/numeric aggregate representations."""

    if value is None:
        return None
    if type(value) is int:
        return value
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise TypeError(f"{label}: non-integral/non-finite database numeric")
        return int(value)
    raise TypeError(f"{label}: unsupported database carrier {type(value).__name__}")


def ensure_money_minor(
    value: object,
    *,
    sign: MoneySign,
    label: str,
    error_code: str = "amount_invalid",
    error_message: str | None = None,
) -> int:
    """Validate one C07-window command value with a stable domain error."""

    try:
        amount = _coerce_input_int(value, label=label)
    except TypeError:
        logger.warning(
            "money command rejected label=%s reason=carrier_type type=%s",
            label,
            type(value).__name__,
        )
        raise AppError(error_code, error_message, status_code=422) from None
    low, high = c07_entry_bounds(sign)
    if not (low <= amount <= high):
        logger.warning(
            "money command rejected label=%s reason=range direction=%s",
            label,
            "low" if amount < low else "high",
        )
        raise AppError(error_code, error_message, status_code=422)
    return amount


def ensure_optional_money_minor(
    value: object | None,
    *,
    sign: MoneySign,
    label: str,
    error_code: str = "amount_invalid",
    error_message: str | None = None,
) -> int | None:
    """Validate an optional C07-window command value."""

    if value is None:
        return None
    return ensure_money_minor(
        value,
        sign=sign,
        label=label,
        error_code=error_code,
        error_message=error_message,
    )


def parse_canonical_money_minor(
    value: object,
    *,
    sign: MoneySign,
    label: str,
    error_code: str = "amount_invalid",
    error_message: str | None = None,
) -> int:
    """Parse an exact base-10 form value before applying the command gate."""

    if not is_canonical_money_minor_text(value):
        raise AppError(error_code, error_message, status_code=422)
    return ensure_money_minor(
        int(value, 10),
        sign=sign,
        label=label,
        error_code=error_code,
        error_message=error_message,
    )


def projection_sum_to_int(
    value: object,
    *,
    label: str,
    empty_is_zero: bool = False,
) -> int:
    """Materialize a read projection without hiding an unexpected SQL NULL."""

    try:
        total = _coerce_database_integer(value, label=label)
    except TypeError:
        logger.error(
            "money projection rejected label=%s reason=non_exact type=%s",
            label,
            type(value).__name__,
        )
        raise AppError("money_projection_out_of_range", status_code=500) from None
    if total is None:
        if empty_is_zero:
            return 0
        logger.error("money projection rejected label=%s reason=null", label)
        raise AppError("money_projection_out_of_range", status_code=500)
    if not (-MONEY_AGGREGATE_MAX <= total <= MONEY_AGGREGATE_MAX):
        logger.error(
            "money projection rejected label=%s reason=wire_range direction=%s",
            label,
            "low" if total < 0 else "high",
        )
        raise AppError("money_projection_out_of_range", status_code=500)
    return total


def projection_values_sum_to_int(
    values: Iterable[object],
    *,
    label: str,
) -> int:
    """Accumulate exact projection values without an unchecked Python sum."""

    total = 0
    for index, value in enumerate(values):
        item = projection_sum_to_int(
            value,
            label=f"{label}[{index}]",
        )
        total = projection_sum_to_int(
            total + item,
            label=label,
        )
    return total


def fold_sum_to_int(
    value: object,
    *,
    label: str,
    empty_is_zero: bool = False,
) -> int:
    """Materialize a write-fold aggregate; failure aborts the transaction."""

    try:
        total = _coerce_database_integer(value, label=label)
    except TypeError:
        logger.error(
            "money fold rejected label=%s reason=non_exact type=%s",
            label,
            type(value).__name__,
        )
        raise AppError("money_fold_conflict", status_code=409) from None
    if total is None:
        if empty_is_zero:
            return 0
        logger.error("money fold rejected label=%s reason=null", label)
        raise AppError("money_fold_conflict", status_code=409)
    if not (-MONEY_AGGREGATE_MAX <= total <= MONEY_AGGREGATE_MAX):
        logger.error(
            "money fold rejected label=%s reason=aggregate_range direction=%s",
            label,
            "low" if total < 0 else "high",
        )
        raise AppError("money_fold_conflict", status_code=409)
    return total


def round_minor_ratio_half_up(
    numerator: int,
    denominator: int,
    *,
    label: str,
) -> int:
    """Round an exact integer ratio to minor units, with ties away from zero."""

    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        logger.error(
            "money ratio rejected label=%s numerator_type=%s denominator_type=%s",
            label,
            type(numerator).__name__,
            type(denominator).__name__,
        )
        raise AppError("money_projection_out_of_range", status_code=500)
    magnitude, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 >= denominator:
        magnitude += 1
    rounded = -magnitude if numerator < 0 else magnitude
    return projection_sum_to_int(rounded, label=label)


def projection_values_average_to_int(
    values: Iterable[object],
    *,
    label: str,
) -> int:
    """Average exact projection values without bounding the numerator early.

    Every source value is checked at the wire boundary.  The intermediate
    numerator deliberately remains a Python arbitrary-precision integer so a
    representable average is not rejected merely because its exact sum is
    wider than the final projection contract.
    """

    total = 0
    count = 0
    for index, value in enumerate(values):
        total += projection_sum_to_int(value, label=f"{label}[{index}]")
        count += 1
    if count == 0:
        return 0
    return round_minor_ratio_half_up(total, count, label=label)
