"""ADR-0029 cross-ledger bill split DTOs.

Two response shapes — strictly separated:

- :class:`BillSplitSentResponse` — sender view of an invitation they
  created. **Does not** expose ``receiver_ledger_id``; sender never knows
  which ledger receiver accepted to.

- :class:`BillSplitInboxResponse` — receiver view of an invitation
  addressed to them. **Does not** expose ``sender_ledger_id`` or
  ``sender_expense_id``; receiver never sees sender's internal IDs.

The schema separation is the single load-bearing privacy boundary
(ADR-0029 + ADR-0022). Don't merge them. Don't reuse a single
``BillSplitResponse`` everywhere.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "BillSplitAcceptRequest",
    "BillSplitInboxResponse",
    "BillSplitInboxListResponse",
    "BillSplitInviteRequest",
    "BillSplitSentResponse",
    "BillSplitSentListResponse",
    "BillSplitStatus",
]

BillSplitStatus = Literal["invited", "accepted", "rejected", "cancelled", "expired"]


class BillSplitInviteRequest(BaseModel):
    """Body for ``POST /api/expenses/{id}/split-invite``.

    NOTE the absence of ``receiver_ledger_id`` — see ADR-0029 Q0. Sender
    must NOT specify which ledger receiver accepts to; receiver picks
    that at accept time.
    """

    receiver_account_id: int = Field(gt=0)
    amount_cents: int = Field(gt=0)


class BillSplitAcceptRequest(BaseModel):
    """Body for ``POST /api/bill-splits/{public_id}/accept``.

    Receiver picks the target ledger. Backend checks write permission.
    """

    target_ledger_id: str = Field(min_length=1, max_length=64)


class _BillSplitCommon(BaseModel):
    """Fields safe to expose to both sender and receiver views."""

    model_config = ConfigDict(from_attributes=True)

    public_id: str
    status: BillSplitStatus
    amount_cents: int
    home_currency_code: str
    original_currency_code: str
    original_amount_minor: int | None = None
    exchange_rate_to_cny: Decimal | None = None
    exchange_rate_date: datetime | None = None
    exchange_rate_source: str | None = None
    merchant_snapshot: str | None = None
    category_suggestion: str | None = None
    expense_time_snapshot: datetime | None = None
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    cancelled_at: datetime | None = None
    expired_at: datetime | None = None

    @field_serializer(
        "exchange_rate_date", "expense_time_snapshot",
        "expires_at", "created_at", "accepted_at",
        "rejected_at", "cancelled_at", "expired_at",
    )
    def _ser_dt(self, value: datetime | None) -> str | None:
        return to_iso(value)

    @field_serializer("exchange_rate_to_cny")
    def _ser_rate(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None


class BillSplitSentResponse(_BillSplitCommon):
    """Sender's view of one of their own invitations.

    Includes who they sent it to (receiver_account_id + display name) and
    sender's own internal context (sender_expense_id is OK here — sender
    owns this), but **never** ``receiver_ledger_id`` (privacy: sender
    must not learn which ledger receiver accepted to).
    """

    receiver_account_id: int
    receiver_display_name_snapshot: str | None = None
    sender_expense_id: int


class BillSplitInboxResponse(_BillSplitCommon):
    """Receiver's view of an invitation addressed to them.

    Carries who sent it (sender_account_id + display name) but **never**
    sender's expense_id or ledger_id (privacy: receiver must not pierce
    into sender's personal ledger).
    """

    sender_account_id: int
    sender_display_name: str


class BillSplitSentListResponse(BaseModel):
    items: list[BillSplitSentResponse] = Field(default_factory=list)


class BillSplitInboxListResponse(BaseModel):
    items: list[BillSplitInboxResponse] = Field(default_factory=list)
