"""Public contracts for Expense refund, chargeback, and reversal facts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas._expense import ExpenseResponse
from app.schemas._money import (
    NonNegativeMoneyAggregate,
    PositiveMoneyMinor,
    SignedMoneyAggregate,
)
from app.services.time_service import to_iso

ExpenseOffsetKind = Literal["refund", "chargeback", "reversal"]
ExpenseOffsetStatus = Literal["active", "voided"]

__all__ = [
    "ExpenseFactBundleResponse",
    "ExpenseFinancialSummary",
    "ExpenseOffsetCreateRequest",
    "ExpenseOffsetKind",
    "ExpenseOffsetResponse",
    "ExpenseOffsetRevisionResponse",
    "ExpenseOffsetStatus",
]


class ExpenseOffsetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExpenseOffsetKind
    original_amount_minor: PositiveMoneyMinor | None = None
    accounting_date: date
    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int = Field(ge=1)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("offset reason is required")
        return cleaned

    @model_validator(mode="after")
    def _amount_matches_kind(self) -> ExpenseOffsetCreateRequest:
        if self.kind == "reversal" and self.original_amount_minor is not None:
            raise ValueError("reversal amount is server-owned")
        if self.kind != "reversal" and self.original_amount_minor is None:
            raise ValueError("refund amount is required")
        return self


class ExpenseOffsetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    public_id: str
    kind: ExpenseOffsetKind
    status: ExpenseOffsetStatus
    original_currency_code: str
    original_amount_minor: PositiveMoneyMinor
    home_currency_code: str
    amount_cents: PositiveMoneyMinor
    exchange_rate_to_cny: Decimal | None
    accounting_date: date
    category: str
    reason: str
    row_version: int
    fact_revision: int
    created_at: datetime
    updated_at: datetime
    voided_at: datetime | None

    @field_serializer("created_at", "updated_at", "voided_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)

    @field_serializer("exchange_rate_to_cny")
    def _serialize_rate(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None


class ExpenseOffsetRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_id: str
    offset_public_id: str
    revision_number: int
    change_kind: Literal["created", "correction", "void"]
    reason: str
    before: dict[str, Any] | None
    after: dict[str, Any]
    actor_account_name: str | None = None
    actor_device_name: str | None = None
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return to_iso(value)


class ExpenseFinancialSummary(BaseModel):
    gross_original_minor: NonNegativeMoneyAggregate
    gross_home_amount_cents: NonNegativeMoneyAggregate
    active_refunded_original_minor: NonNegativeMoneyAggregate
    remaining_refundable_original_minor: NonNegativeMoneyAggregate
    lineage_home_net_cents: SignedMoneyAggregate
    fx_difference_cents: SignedMoneyAggregate
    status: Literal["confirmed", "partially_refunded", "fully_refunded", "reversed"]


class ExpenseFactBundleResponse(BaseModel):
    root: ExpenseResponse
    financial_summary: ExpenseFinancialSummary
    active_offsets: list[ExpenseOffsetResponse]
    recent_history: list[ExpenseOffsetRevisionResponse] = Field(default_factory=list)
