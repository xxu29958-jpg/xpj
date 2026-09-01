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
    "ExpenseRelationshipImpacts",
]

ExpenseRelationshipReason = Literal[
    "source_refunded",
    "source_chargeback",
    "source_reversed",
]


class CancelledPendingInvitationImpact(BaseModel):
    invitation_public_id: str
    cancellation_reason_code: ExpenseRelationshipReason


class AcceptedInvitationImpact(BaseModel):
    invitation_public_id: str
    source_reason_code: ExpenseRelationshipReason
    receiver_display_name: str | None = None
    debt_public_id: str | None = None
    original_agreed_share_home_minor: NonNegativeMoneyAggregate
    suggested_net_share_home_minor: NonNegativeMoneyAggregate
    suggested_action: Literal["review_split"] = "review_split"


class ExpenseRelationshipImpacts(BaseModel):
    pending_invites_cancelled: list[CancelledPendingInvitationImpact] = Field(default_factory=list)
    accepted_impacts: list[AcceptedInvitationImpact] = Field(default_factory=list)


class ExpenseOffsetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExpenseOffsetKind
    original_amount_minor: PositiveMoneyMinor | None = None
    accounting_date: date
    reason: str = Field(min_length=1, max_length=500)
    # ``0`` is the existing device-local first-write sentinel. A server-id
    # mutation carrying it still reaches the OCC CAS and conflicts because
    # persisted Expense versions start at 1.
    expected_row_version: int = Field(ge=0)

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
    exchange_rate_date: date | None
    exchange_rate_source: str | None
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
    relationship_impacts: ExpenseRelationshipImpacts = Field(default_factory=ExpenseRelationshipImpacts)
