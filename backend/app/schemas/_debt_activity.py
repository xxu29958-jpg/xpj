"""Participant-visible relationship history; events never constitute a new fold."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_serializer

from app.schemas._debts import MemberRepaymentProposalResponse, RepaymentFactResponse
from app.schemas._money import SignedMoneyMinor
from app.services.time_service import to_iso


class DebtActivityResponse(BaseModel):
    # The pair (kind, public_id) is the stable event identity. Proposal creation
    # and resolution deliberately share their proposal's public identity.
    kind: Literal[
        "created", "repayment", "repayment_void", "adjustment", "forgiveness",
        "debt_void", "proposal_created", "proposal_resolved",
    ]
    public_id: str
    recorded_at: datetime
    actor_display_name: str | None = None
    actor_is_you: bool
    amount_cents: SignedMoneyMinor | None = None
    reason: str | None = None
    repayment: RepaymentFactResponse | None = None
    proposal: MemberRepaymentProposalResponse | None = None

    @field_serializer("recorded_at")
    def serialize_recorded_at(self, value: datetime) -> str:
        return to_iso(value)


class DebtActivityListResponse(BaseModel):
    debt_public_id: str
    home_currency_code: str
    items: list[DebtActivityResponse]
    page: int
    page_size: int
    total: int
