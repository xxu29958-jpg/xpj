"""CSV import batch / row / apply payloads."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas._money import NonNegativeMoneyMinor, PositiveCanonicalDecimalInput, SignedMoneyAggregate
from app.services.time_service import to_iso

__all__ = [
    "CsvImportApplyRequest",
    "CsvImportApplyResponse",
    "CsvImportBatchResponse",
    "CsvImportRowResponse",
    "CsvImportRowsResponse",
    "CsvImportReviewRequest",
]


class CsvImportBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    file_name: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    applied_rows: int
    inserted_count: int
    matched_rows: int = 0
    review_rows: int = 0
    confirmed_offset_rows: int = 0
    locked_until: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None

    @field_serializer("locked_until", "created_at", "updated_at", "applied_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class CsvImportRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_number: int
    status: str
    error_code: str | None
    error_message: str | None
    amount_cents: NonNegativeMoneyMinor | None
    home_currency_code: str | None
    original_currency_code: str | None
    original_amount_minor: NonNegativeMoneyMinor | None
    exchange_rate_to_cny: Decimal | None
    exchange_rate_date: date | None
    exchange_rate_source: str | None
    merchant: str | None
    category: str
    note: str | None
    expense_time: datetime | None
    tags: str | None
    source: str
    expense_id: int | None
    entry_kind: str = "expense"
    offset_kind: str | None = None
    source_event_public_id: str | None = None
    source_root_public_id: str | None = None
    accounting_date: date | None = None
    stream_amount_cents: SignedMoneyAggregate | None = None
    lineage_status: str | None = None
    lineage_home_net_cents: SignedMoneyAggregate | None = None
    event_input: dict[str, str] | None = None
    review_reason: str | None = None
    resolved_expense_id: int | None = None
    resolved_offset_public_id: str | None = None
    resolved_root_status: str | None = None
    resolved_root_row_version: int | None = None

    @field_serializer("expense_time")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)

    @field_serializer("exchange_rate_to_cny")
    def serialize_exchange_rate(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None


class CsvImportRowsResponse(BaseModel):
    batch: CsvImportBatchResponse
    items: list[CsvImportRowResponse]
    page: int
    page_size: int
    total: int


class CsvImportApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(default=500, ge=1, le=1000)


class CsvImportApplyResponse(BaseModel):
    batch: CsvImportBatchResponse
    inserted_count: int
    remaining_valid_rows: int


class CsvImportReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expense_id: int | None = Field(default=None, gt=0)
    expected_row_version: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=500)
    acknowledge_incomplete_lineage: bool = False
    manual_exchange_rate: PositiveCanonicalDecimalInput | None = None
    exchange_rate_date: date | None = None

    @model_validator(mode="after")
    def _quote_pair(self):
        if (self.manual_exchange_rate is None) != (self.exchange_rate_date is None):
            raise ValueError("补录汇率和报价日期必须同时提供")
        return self

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("review reason is required")
        return value.strip()
