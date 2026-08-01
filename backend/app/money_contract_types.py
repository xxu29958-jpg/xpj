"""Primitive money bounds and manifest value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MONEY_MINOR_MAX = 9_000_000_000_000
MONEY_AGGREGATE_MAX = 9_007_199_254_740_991
MONEY_CONTRACT_PHASE_KEY = "money_contract_phase"
MONEY_CONTRACT_PHASE_C07 = "c07_money_minor_bigint_v1"


class MoneySign(Enum):
    POSITIVE = "positive"
    NONNEGATIVE = "nonnegative"
    SIGNED = "signed"


def final_sign_bounds(sign: MoneySign) -> tuple[int, int]:
    """Permanent ADR-0073 C07 bounds for one stored fact."""

    if sign is MoneySign.POSITIVE:
        return 1, MONEY_MINOR_MAX
    if sign is MoneySign.NONNEGATIVE:
        return 0, MONEY_MINOR_MAX
    return -MONEY_MINOR_MAX, MONEY_MINOR_MAX


@dataclass(frozen=True)
class MoneyCheck:
    table: str
    column: str
    name: str
    predicate: str


@dataclass(frozen=True)
class RemovedMoneyCheck:
    table: str
    name: str


@dataclass(frozen=True)
class MoneyColumn:
    table: str
    column: str
    sign: MoneySign
    nullable: bool
    server_default: str | None = None
    nonzero: bool = False
    final_predicate_override: str | None = None
    check_table: str | None = None
    additional_checks: tuple[MoneyCheck, ...] = ()

    @property
    def final_check_name(self) -> str:
        return f"ck_{self.check_table or self.table}_{self.column}_money_bounds"

    @property
    def final_check_predicate(self) -> str:
        if self.final_predicate_override is not None:
            return self.final_predicate_override
        low, high = final_sign_bounds(self.sign)
        bounded = f"{self.column} BETWEEN {low} AND {high}"
        if self.nonzero:
            bounded = f"{self.column} <> 0 AND ({bounded})"
        if self.nullable:
            return f"{self.column} IS NULL OR ({bounded})"
        return bounded

    @property
    def final_check(self) -> MoneyCheck:
        return MoneyCheck(
            self.table,
            self.column,
            self.final_check_name,
            self.final_check_predicate,
        )

    @property
    def checks(self) -> tuple[MoneyCheck, ...]:
        return (self.final_check, *self.additional_checks)
