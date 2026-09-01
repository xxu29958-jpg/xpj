"""Confirmed expense, refund, chargeback, and reversal stream contracts."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas._expense import ExpenseResponse
from app.schemas._expense_offset import ExpenseOffsetKind
from app.schemas._money import PositiveMoneyMinor, SignedMoneyAggregate

ExpenseLineageStatus = Literal[
    "confirmed",
    "partially_refunded",
    "fully_refunded",
    "reversed",
]


class ConfirmedExpenseStreamEntry(ExpenseResponse):
    entry_kind: Literal["expense"] = "expense"
    stream_date: date
    stream_amount_cents: SignedMoneyAggregate
    lineage_status: ExpenseLineageStatus
    lineage_home_net_cents: SignedMoneyAggregate


class ConfirmedOffsetStreamEntry(BaseModel):
    entry_kind: Literal["offset"] = "offset"
    public_id: str
    kind: ExpenseOffsetKind
    stream_date: date
    stream_amount_cents: SignedMoneyAggregate
    amount_cents: PositiveMoneyMinor
    original_amount_minor: PositiveMoneyMinor
    original_currency_code: str
    home_currency_code: str
    root_expense_id: int
    root_expense_public_id: str
    root_merchant_label: str | None
    category: str


ConfirmedExpenseStreamItem = Annotated[
    ConfirmedExpenseStreamEntry | ConfirmedOffsetStreamEntry,
    Field(discriminator="entry_kind"),
]


class PaginatedExpensesResponse(BaseModel):
    items: list[ConfirmedExpenseStreamItem]
    page: int
    page_size: int
    total: int


__all__ = [
    "ConfirmedExpenseStreamEntry",
    "ConfirmedExpenseStreamItem",
    "ConfirmedOffsetStreamEntry",
    "ExpenseLineageStatus",
    "PaginatedExpensesResponse",
]
