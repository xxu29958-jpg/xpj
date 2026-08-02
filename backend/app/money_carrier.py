"""Canonical carriers for exact major-unit money input.

Wire money is text so JSON/HTML/CSV parsing cannot silently pass through
binary floating point.  Internal callers may pass an already-exact
``Decimal`` or plain ``int``; bool and float are never money carriers.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

CANONICAL_UNSIGNED_DECIMAL_PATTERN = (
    r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
)
CANONICAL_SIGNED_DECIMAL_PATTERN = (
    rf"-?{CANONICAL_UNSIGNED_DECIMAL_PATTERN}"
)
MAX_MAJOR_DECIMAL_TEXT_LENGTH = 64

_CANONICAL_UNSIGNED_DECIMAL = re.compile(
    rf"{CANONICAL_UNSIGNED_DECIMAL_PATTERN}\Z"
)
_CANONICAL_SIGNED_DECIMAL = re.compile(
    rf"{CANONICAL_SIGNED_DECIMAL_PATTERN}\Z"
)


def parse_canonical_decimal_text(
    value: object,
    *,
    allow_negative: bool = False,
) -> Decimal:
    """Parse the canonical external decimal-string wire format."""

    if type(value) is not str:
        raise ValueError("external money carrier must be text")
    text = value
    if len(text) > MAX_MAJOR_DECIMAL_TEXT_LENGTH:
        raise ValueError("money carrier is too long")
    pattern = (
        _CANONICAL_SIGNED_DECIMAL
        if allow_negative
        else _CANONICAL_UNSIGNED_DECIMAL
    )
    if pattern.fullmatch(text) is None:
        raise ValueError("money carrier is not canonical")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("money carrier is not decimal") from exc
    if not parsed.is_finite():
        raise ValueError("money carrier is not finite")
    if parsed.is_zero() and parsed.is_signed():
        raise ValueError("negative zero is not canonical")
    return parsed


def validate_exact_decimal(
    value: object,
    *,
    allow_negative: bool = False,
) -> Decimal:
    """Validate an already-exact internal Decimal/int without re-serializing it."""

    if type(value) is Decimal:
        parsed = value
    elif type(value) is int:
        parsed = Decimal(value)
    else:
        raise ValueError("unsupported exact decimal carrier")
    if not parsed.is_finite():
        raise ValueError("money carrier is not finite")
    if parsed.is_zero() and parsed.is_signed():
        raise ValueError("negative zero is not canonical")
    if not allow_negative and parsed < 0:
        raise ValueError("money carrier has an invalid sign")
    return parsed


def parse_canonical_major_decimal(
    value: object,
    *,
    allow_negative: bool = False,
) -> Decimal:
    """Dispatch external text and internal exact carriers without conflation."""

    if type(value) is str:
        return parse_canonical_decimal_text(
            value,
            allow_negative=allow_negative,
        )
    return validate_exact_decimal(value, allow_negative=allow_negative)


__all__ = [
    "CANONICAL_SIGNED_DECIMAL_PATTERN",
    "CANONICAL_UNSIGNED_DECIMAL_PATTERN",
    "MAX_MAJOR_DECIMAL_TEXT_LENGTH",
    "parse_canonical_decimal_text",
    "parse_canonical_major_decimal",
    "validate_exact_decimal",
]
