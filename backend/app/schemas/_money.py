"""Shared strict JSON request money types for ADR-0073 C07.

Minor-unit inputs are strict integers. Major-unit inputs are canonical decimal
strings on the JSON wire; trusted internal adapters may pass an exact
``Decimal`` after parsing their own non-JSON transport.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, WithJsonSchema

from app.money_carrier import (
    CANONICAL_UNSIGNED_DECIMAL_PATTERN,
    MAX_MAJOR_DECIMAL_TEXT_LENGTH,
    parse_canonical_decimal_text,
    validate_exact_decimal,
)
from app.money_contract import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX

_INT64_SCHEMA = {"format": "int64"}
CANONICAL_NONNEGATIVE_MONEY_MINOR_TEXT_PATTERN = r"^(?:0|[1-9][0-9]{0,12})$"

PositiveMoneyMinor = Annotated[
    int,
    Field(
        strict=True,
        ge=1,
        le=MONEY_MINOR_MAX,
        json_schema_extra=_INT64_SCHEMA,
    ),
]
NonNegativeMoneyMinor = Annotated[
    int,
    Field(
        strict=True,
        ge=0,
        le=MONEY_MINOR_MAX,
        json_schema_extra=_INT64_SCHEMA,
    ),
]
SignedMoneyMinor = Annotated[
    int,
    Field(
        strict=True,
        ge=-MONEY_MINOR_MAX,
        le=MONEY_MINOR_MAX,
        json_schema_extra=_INT64_SCHEMA,
    ),
]


def _validate_nonzero_money_minor(value: int) -> int:
    if value == 0:
        raise ValueError("value must not be zero")
    return value


NonZeroSignedMoneyMinor = Annotated[
    int,
    Field(
        strict=True,
        ge=-MONEY_MINOR_MAX,
        le=MONEY_MINOR_MAX,
        json_schema_extra={"format": "int64", "not": {"const": 0}},
    ),
    AfterValidator(_validate_nonzero_money_minor),
]

# Read projections may add multiple bounded facts. They remain inside the
# RFC-8259 / ECMAScript exact-integer envelope enforced by projection helpers.
PositiveMoneyAggregate = Annotated[
    int,
    Field(
        strict=True,
        ge=1,
        le=MONEY_AGGREGATE_MAX,
        json_schema_extra=_INT64_SCHEMA,
    ),
]
NonNegativeMoneyAggregate = Annotated[
    int,
    Field(
        strict=True,
        ge=0,
        le=MONEY_AGGREGATE_MAX,
        json_schema_extra=_INT64_SCHEMA,
    ),
]
SignedMoneyAggregate = Annotated[
    int,
    Field(
        strict=True,
        ge=-MONEY_AGGREGATE_MAX,
        le=MONEY_AGGREGATE_MAX,
        json_schema_extra=_INT64_SCHEMA,
    ),
]
NonNegativeMoneyMinorText = Annotated[
    str,
    Field(
        pattern=CANONICAL_NONNEGATIVE_MONEY_MINOR_TEXT_PATTERN,
        max_length=len(str(MONEY_MINOR_MAX)),
    ),
]

CANONICAL_NONNEGATIVE_DECIMAL_INPUT_PATTERN = (
    rf"^{CANONICAL_UNSIGNED_DECIMAL_PATTERN}$"
)
CANONICAL_POSITIVE_DECIMAL_INPUT_PATTERN = (
    r"^(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)$"
)


def expense_item_money_schema_extra() -> dict[str, object]:
    """Return the kind-sensitive C07 amount schema for receipt items."""

    def amount_schema(minimum: int, maximum: int) -> dict[str, object]:
        return {
            "anyOf": [
                {
                    "type": "integer",
                    "format": "int64",
                    "minimum": minimum,
                    "maximum": maximum,
                },
                {"type": "null"},
            ]
        }

    return {
        "allOf": [
            {
                "if": {
                    "properties": {"kind": {"const": "discount"}},
                    "required": ["kind"],
                },
                "then": {
                    "properties": {
                        "amount_cents": amount_schema(-MONEY_MINOR_MAX, 0)
                    }
                },
                "else": {
                    "properties": {
                        "amount_cents": amount_schema(0, MONEY_MINOR_MAX)
                    }
                },
            }
        ]
    }


def _parse_canonical_decimal_input(value: object) -> Decimal:
    """Require JSON/HTTP strings while allowing explicit internal Decimal."""

    if type(value) not in {str, Decimal}:
        raise ValueError("value must be a canonical decimal string")
    if type(value) is str:
        return parse_canonical_decimal_text(value)
    return validate_exact_decimal(value)


def _validate_positive_canonical_decimal(value: Decimal) -> Decimal:
    """Reject every zero representation after exact canonical parsing."""

    if value <= 0:
        raise ValueError("value must be greater than zero")
    return value


NonNegativeCanonicalDecimalInput = Annotated[
    Decimal,
    BeforeValidator(_parse_canonical_decimal_input),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": CANONICAL_NONNEGATIVE_DECIMAL_INPUT_PATTERN,
            "maxLength": MAX_MAJOR_DECIMAL_TEXT_LENGTH,
        },
        mode="validation",
    ),
]
PositiveCanonicalDecimalInput = Annotated[
    Decimal,
    BeforeValidator(_parse_canonical_decimal_input),
    AfterValidator(_validate_positive_canonical_decimal),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": CANONICAL_POSITIVE_DECIMAL_INPUT_PATTERN,
            "maxLength": MAX_MAJOR_DECIMAL_TEXT_LENGTH,
        },
        mode="validation",
    ),
]

__all__ = [
    "CANONICAL_NONNEGATIVE_DECIMAL_INPUT_PATTERN",
    "CANONICAL_NONNEGATIVE_MONEY_MINOR_TEXT_PATTERN",
    "CANONICAL_POSITIVE_DECIMAL_INPUT_PATTERN",
    "NonNegativeCanonicalDecimalInput",
    "NonNegativeMoneyAggregate",
    "NonNegativeMoneyMinor",
    "NonNegativeMoneyMinorText",
    "NonZeroSignedMoneyMinor",
    "PositiveCanonicalDecimalInput",
    "PositiveMoneyAggregate",
    "PositiveMoneyMinor",
    "SignedMoneyAggregate",
    "SignedMoneyMinor",
    "expense_item_money_schema_extra",
]
