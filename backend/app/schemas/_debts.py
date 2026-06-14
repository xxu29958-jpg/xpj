"""ADR-0049 Debt domain CRUD payloads.

Slice 1: create / list / get. Slice 2 adds the fold-changing write requests
(repayment / adjustment / repayment-void / debt-void). Every write request
carries ``expected_row_version`` (§3.6 — part of the [[0042]] fingerprint and
the §2.1 stale-intent check) and replies with the fold-after ``DebtResponse``
so the client gets the fresh ``row_version`` for its next ``expected``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "DebtAdjustmentCreateRequest",
    "DebtCreateRequest",
    "DebtListResponse",
    "DebtResponse",
    "DebtVoidCreateRequest",
    "RepaymentCreateRequest",
    "RepaymentCreateResponse",
    "RepaymentVoidCreateRequest",
]


class DebtCreateRequest(BaseModel):
    """Create one external/manual Debt (ADR-0049 §2 / §5.1).

    ``principal_amount_cents`` is the home-currency principal for a home-currency
    Debt. For a foreign-currency Debt the client submits ``original_currency`` +
    ``original_amount`` (+ optional ``event_time``); the backend freezes the
    home principal from the [[0027]] snapshot and rejects the request when the
    rate is still pending (§2.2). Clients MUST NOT submit exchange rates or
    compute home amounts.
    """

    model_config = ConfigDict(extra="forbid")

    direction: str
    counterparty_type: str
    counterparty_account_id: int | None = None
    counterparty_label: str | None = Field(default=None, max_length=255)
    principal_amount_cents: int | None = Field(default=None, gt=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, gt=0)
    event_time: datetime | None = None
    source_type: str = "manual"


class DebtResponse(BaseModel):
    public_id: str
    ledger_id: str
    direction: str
    counterparty_type: str
    counterparty_account_id: int | None = None
    counterparty_label: str | None = None
    principal_amount_cents: int
    remaining_amount_cents: int
    paid_amount_cents: int
    status: str
    source_type: str
    source_id: str | None = None
    home_currency_code: str
    original_currency_code: str | None = None
    original_amount_minor: int | None = None
    exchange_rate_to_cny: Decimal | None = None
    exchange_rate_date: datetime | None = None
    exchange_rate_source: str | None = None
    created_at: datetime
    updated_at: datetime
    row_version: int

    @field_serializer("created_at", "updated_at", "exchange_rate_date")
    def serialize_debt_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class DebtListResponse(BaseModel):
    items: list[DebtResponse]


class RepaymentCreateResponse(DebtResponse):
    """Fold-after Debt response plus the committed repayment id for void flows."""

    repayment_public_id: str


class RepaymentCreateRequest(BaseModel):
    """Record one committed repayment fact (ADR-0049 §3.1).

    Home-currency repayment submits ``amount_cents``. A foreign-currency
    repayment submits ``original_currency`` + ``original_amount`` (+ optional
    ``paid_at``); the backend freezes the home ``amount_cents`` from the [[0027]]
    snapshot for ``paid_at`` and rejects when the rate is pending (§2.2). The two
    amount inputs are mutually exclusive. ``expected_row_version`` is the §2.1
    stale-intent token + §3.6 fingerprint component. The debtor "I paid"
    proposal (``proposal_id``) is slice 3 and is NOT accepted here.
    """

    model_config = ConfigDict(extra="forbid")

    amount_cents: int | None = Field(default=None, gt=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, gt=0)
    paid_at: datetime | None = None
    expected_row_version: int


class DebtAdjustmentCreateRequest(BaseModel):
    """Record one signed principal-like correction (ADR-0049 §3.3).

    ``amount_cents`` is a signed home-currency delta (may be negative to lower
    ``remaining``; never to push it below 0). ``reason`` is required.
    ``expected_row_version`` is the §2.1 stale-intent token + §3.6 fingerprint
    component.
    """

    model_config = ConfigDict(extra="forbid")

    amount_cents: int
    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int


class RepaymentVoidCreateRequest(BaseModel):
    """Void one mistaken repayment (ADR-0049 §3.4).

    ``repayment_public_id`` identifies the repayment to void; it must belong to
    this Debt. ``reason`` is required. The original repayment row is never
    deleted (the void is append-only and excludes it from the fold).
    """

    model_config = ConfigDict(extra="forbid")

    repayment_public_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int


class DebtVoidCreateRequest(BaseModel):
    """Void an entire Debt (ADR-0049 §3.5). ``reason`` is required."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    expected_row_version: int
