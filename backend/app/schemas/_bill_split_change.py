"""Participant-safe accepted-split changes; private expense records stay private."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas._debts import DebtResponse
from app.schemas._money import (
    NonNegativeMoneyAggregate,
    NonNegativeMoneyMinor,
    SignedMoneyAggregate,
    SignedMoneyMinor,
)
from app.services.time_service import to_iso


class BillSplitChangeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_share_amount_cents: NonNegativeMoneyMinor
    settlement_net_amount_cents: SignedMoneyMinor
    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int = Field(ge=1)
    expected_return_row_version: int | None = Field(default=None, ge=1)
    supersedes_proposal_public_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned


class BillSplitChangeAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(ge=1)
    expected_return_row_version: int | None = Field(default=None, ge=1)


class BillSplitChangeProposalResponse(BaseModel):
    public_id: str
    original_debt_public_id: str
    return_debt_public_id: str | None = None
    status: Literal["pending", "accepted", "rejected", "withdrawn", "superseded", "expired"]
    proposed_by_you: bool
    share_before_amount_cents: NonNegativeMoneyMinor
    new_share_amount_cents: NonNegativeMoneyMinor
    settlement_before_net_amount_cents: SignedMoneyAggregate
    settlement_net_amount_cents: SignedMoneyMinor
    original_paid_amount_cents: NonNegativeMoneyAggregate
    return_paid_amount_cents: NonNegativeMoneyAggregate
    original_forgiven_amount_cents: NonNegativeMoneyAggregate
    return_forgiven_amount_cents: NonNegativeMoneyAggregate
    original_debt_row_version: int
    return_debt_row_version: int | None = None
    reason: str
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None

    @field_serializer("created_at", "expires_at", "resolved_at")
    def serialize_time(self, value: datetime | None) -> str | None:
        return to_iso(value)


class BillSplitSettlementPreviewResponse(BaseModel):
    new_share_amount_cents: NonNegativeMoneyMinor
    default_settlement_net_amount_cents: SignedMoneyMinor
    cash_based_settlement_net_amount_cents: SignedMoneyAggregate | None
    requires_explicit_settlement: bool


class BillSplitAgreementResponse(BaseModel):
    invitation_public_id: str
    home_currency_code: str
    original_share_amount_cents: NonNegativeMoneyMinor
    agreed_share_amount_cents: NonNegativeMoneyMinor
    original_debt: DebtResponse
    return_debt: DebtResponse | None = None
    viewer_is_party: bool
    original_paid_amount_cents: NonNegativeMoneyAggregate
    return_paid_amount_cents: NonNegativeMoneyAggregate
    original_forgiven_amount_cents: NonNegativeMoneyAggregate
    return_forgiven_amount_cents: NonNegativeMoneyAggregate
    settlement_net_amount_cents: SignedMoneyAggregate
    pending_repayment_debt_public_ids: list[str] = Field(default_factory=list)
    pending_proposal: BillSplitChangeProposalResponse | None = None
    preview: BillSplitSettlementPreviewResponse
