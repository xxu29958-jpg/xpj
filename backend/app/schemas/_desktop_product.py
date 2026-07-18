"""Projection and command contracts for the native Desktop product window.

The Desktop Manager never owns a business credential or talks to PostgreSQL.
The backend keeps ledger selection and all business reads authoritative, then
normalizes heterogeneous domains into bounded domain/inspector projections.
Inbox mutations stay backend-owned and carry the same permission, OCC, and
idempotency fences as the other product surfaces.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DesktopWorkspaceKey = Literal["inbox", "transactions", "obligations", "plans", "insights"]


class DesktopProductField(BaseModel):
    label: str
    value: str


class DesktopInboxEdit(BaseModel):
    expected_row_version: int
    amount_minor: int | None = None
    currency_code: str
    currency_symbol: str
    minor_unit_digits: int = Field(ge=0, le=3)
    home_amount_minor: int | None = None
    home_currency_code: str
    original_amount_minor: int | None = None
    original_currency_code: str
    exchange_rate_to_home: Decimal | None = None
    exchange_rate_date: date | None = None
    exchange_rate_source: str | None = None
    fx_status: str
    merchant: str
    category: str


class DesktopProductRow(BaseModel):
    key: str
    kind: str
    title: str
    subtitle: str = ""
    status: str
    status_label: str
    amount_minor: int | None = None
    currency_code: str | None = None
    value_text: str | None = None
    occurred_at: str | None = None
    occurred_precision: Literal["instant", "date"] | None = None
    fields: list[DesktopProductField] = Field(default_factory=list)
    capabilities: list[Literal["save", "confirm", "ignore"]] = Field(default_factory=list)
    edit: DesktopInboxEdit | None = None


class DesktopProductLedger(BaseModel):
    ledger_id: str
    name: str
    role: str
    is_default: bool
    is_current: bool


class DesktopWorkspaceResponse(BaseModel):
    workspace: DesktopWorkspaceKey
    title: str
    ledger_id: str
    ledger_name: str
    role: str
    generated_at: datetime
    rows: list[DesktopProductRow]
    total_count: int
    truncated: bool = False
    empty_title: str
    empty_detail: str
    ledgers: list[DesktopProductLedger]


class DesktopInboxCommandRequest(BaseModel):
    """One user intent against the currently selected pending expense."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["save", "confirm", "ignore"]
    expected_row_version: int = Field(ge=1)
    original_amount_minor: int | None = Field(default=None, ge=0)
    original_currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    home_amount_minor: int | None = Field(default=None, ge=0)
    home_currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    exchange_rate_to_home: Decimal | None = Field(default=None, gt=0)
    exchange_rate_date: date | None = None
    exchange_rate_source: str | None = Field(default=None, max_length=32)
    fx_status: str | None = Field(default=None, max_length=32)
    merchant: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_action_fields(self) -> DesktopInboxCommandRequest:
        editable = {"original_amount_minor", "merchant", "category"} & self.model_fields_set
        money_snapshot = {
            "original_currency_code",
            "home_amount_minor",
            "home_currency_code",
            "exchange_rate_to_home",
            "exchange_rate_date",
            "exchange_rate_source",
            "fx_status",
        }
        has_money_edit = "original_amount_minor" in self.model_fields_set
        has_money_snapshot = bool(money_snapshot & self.model_fields_set)
        if has_money_edit and not money_snapshot.issubset(self.model_fields_set):
            raise ValueError("amount edit requires the complete frozen currency snapshot")
        if has_money_snapshot and not has_money_edit:
            raise ValueError("currency snapshot requires an amount edit")
        if self.action == "save" and not editable:
            raise ValueError("save requires at least one editable field")
        if self.action == "ignore" and editable:
            raise ValueError("ignore does not accept editable fields")
        return self


class DesktopInboxCommandResponse(BaseModel):
    action: Literal["save", "confirm", "ignore"]
    message: str
    expense_status: str
    row_version: int
