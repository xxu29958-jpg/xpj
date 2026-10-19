"""One shared protocol for the existing Web and Android funds consumers."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas._money import NonNegativeMoneyMinor, SignedMoneyAggregate
from app.services.currency_common import normalize_currency_code


class EnvelopeSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=0)
    home_currency_code: str
    account_public_ids: list[str] = Field(max_length=100)
    account_row_versions: dict[str, int] = Field(max_length=100)
    allocations: dict[str, NonNegativeMoneyMinor] = Field(max_length=100)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("home_currency_code")
    @classmethod
    def currency(cls, value: str) -> str:
        return normalize_currency_code(value)


class EnvelopeAccountView(BaseModel):
    public_id: str
    name: str
    currency_code: str
    balance_minor: SignedMoneyAggregate | None
    row_version: int
    selected: bool
    can_select: bool


class EnvelopePurposeView(BaseModel):
    purpose: str
    label: str
    planned_minor: SignedMoneyAggregate | None
    funded: bool
    allocated_minor: NonNegativeMoneyMinor
    spent_minor: SignedMoneyAggregate | None
    unpaid_credit_minor: SignedMoneyAggregate | None
    unlinked_minor: SignedMoneyAggregate | None
    available_minor: SignedMoneyAggregate | None
    reserved_minor: SignedMoneyAggregate | None


class EnvelopeMonthView(BaseModel):
    month: str
    reserved_minor: SignedMoneyAggregate | None


class EnvelopeSummary(BaseModel):
    ledger_id: str
    month: str
    home_currency_code: str
    row_version: int
    read_at: datetime
    valuation_date: date
    cash_minor: SignedMoneyAggregate | None
    reserved_minor: SignedMoneyAggregate | None
    unassigned_minor: SignedMoneyAggregate | None


class EnvelopeReceipt(EnvelopeSummary):
    """Bounded acceptance result; sources, purposes and month history are GET data."""
    receipt_revision: Literal[1] = 1
    # Old Android writers require these keys but only use the acceptance fields.
    # Empty tuples prevent a future caller from persisting a read model here.
    accounts: tuple[()] = ()
    purposes: tuple[()] = ()
    months: tuple[()] = ()
    notices: tuple[()] = ()


class EnvelopesView(EnvelopeSummary):
    accounts: list[EnvelopeAccountView]
    purposes: list[EnvelopePurposeView]
    months: list[EnvelopeMonthView]
    notices: list[str]


class EnvelopeRevisionView(BaseModel):
    row_version: int
    month: str
    reason: str
    allocation_snapshot: dict
    recorded_at: datetime
