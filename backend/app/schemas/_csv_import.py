"""CSV import batch / row / apply payloads."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso


__all__ = [
    "CsvImportApplyRequest",
    "CsvImportApplyResponse",
    "CsvImportBatchResponse",
    "CsvImportRowResponse",
    "CsvImportRowsResponse",
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
    amount_cents: int | None
    original_currency_code: str | None
    original_amount_minor: int | None
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
    batch_size: int = Field(default=500, ge=1, le=1000)


class CsvImportApplyResponse(BaseModel):
    batch: CsvImportBatchResponse
    inserted_count: int
    remaining_valid_rows: int
