"""ADR-0049 Debt domain CRUD payloads (slice 1: create / list / get)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "DebtCreateRequest",
    "DebtListResponse",
    "DebtResponse",
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
