"""FX rate request/response models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.fx_constants import FX_SOURCE_MANUAL
from app.schemas._money import PositiveCanonicalDecimalInput
from app.services.time_service import to_iso

__all__ = [
    "ExchangeRateListResponse",
    "ExchangeRateRequest",
    "ExchangeRateResponse",
    "ProjectionReferenceDto",
]


class ExchangeRateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency_code: str = Field(min_length=3, max_length=3)
    home_currency_code: str = Field(min_length=3, max_length=3)
    rate_date: date
    rate_to_cny: PositiveCanonicalDecimalInput
    source: str | None = Field(default=FX_SOURCE_MANUAL, max_length=32)
    expected_row_version: int = Field(ge=0, strict=True)


class ExchangeRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    currency_code: str
    home_currency_code: str
    rate_date: date
    rate_to_cny: Decimal
    source: str
    created_at: datetime
    updated_at: datetime
    row_version: int = Field(ge=1, strict=True)

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)

    @field_serializer("rate_to_cny")
    def serialize_rate(self, value: Decimal) -> str:
        return format(value, "f")


class ExchangeRateListResponse(BaseModel):
    items: list[ExchangeRateResponse]


class ProjectionReferenceDto(BaseModel):
    """The actual reference date used to value a plan in another currency."""
    model_config = ConfigDict(from_attributes=True)

    source_currency_code: str
    home_currency_code: str
    rate_date: date
