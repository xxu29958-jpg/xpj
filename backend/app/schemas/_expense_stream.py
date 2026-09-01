"""Confirmed expense, refund, chargeback, and reversal stream contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, field_serializer, model_validator

from app.schemas._expense import ExpenseResponse
from app.schemas._expense_offset import ExpenseOffsetKind
from app.schemas._money import PositiveMoneyMinor, SignedMoneyAggregate
from app.services.time_service import to_iso

ExpenseLineageStatus = Literal[
    "confirmed",
    "partially_refunded",
    "fully_refunded",
    "reversed",
]


class ConfirmedOffsetStreamProjection(BaseModel):
    public_id: str
    kind: ExpenseOffsetKind
    amount_cents: PositiveMoneyMinor
    original_amount_minor: PositiveMoneyMinor
    original_currency_code: str
    home_currency_code: str
    category: str


class ConfirmedExpenseStreamItem(BaseModel):
    """One timeline row with enough root context to open it offline."""

    entry_kind: Literal["expense", "offset"]
    stream_date: date
    # Server-owned stable locator. Android persists it only to recover the
    # exact server order after the root/offset tables are observed separately.
    stream_sort_time: datetime
    stream_sort_id: int
    stream_amount_cents: SignedMoneyAggregate
    root: ExpenseResponse
    offset: ConfirmedOffsetStreamProjection | None = None
    # These describe the request-time current root lineage for either row kind.
    lineage_status: ExpenseLineageStatus
    lineage_home_net_cents: SignedMoneyAggregate

    @model_validator(mode="after")
    def _offset_presence_matches_kind(self) -> ConfirmedExpenseStreamItem:
        if (self.entry_kind == "offset") != (self.offset is not None):
            raise ValueError("offset is required exactly for offset entries")
        return self

    @field_serializer("stream_sort_time")
    def _serialize_stream_sort_time(self, value: datetime) -> str:
        return to_iso(value)


class PaginatedExpensesResponse(BaseModel):
    items: list[ConfirmedExpenseStreamItem]
    page: int
    page_size: int
    total: int


__all__ = [
    "ConfirmedExpenseStreamItem",
    "ConfirmedOffsetStreamProjection",
    "ExpenseLineageStatus",
    "PaginatedExpensesResponse",
]
