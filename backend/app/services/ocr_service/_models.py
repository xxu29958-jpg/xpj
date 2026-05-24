"""OCR DTO + provider protocol + draft-field constants (leaf module)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.models import Expense


@dataclass(frozen=True)
class OcrResult:
    raw_text: str
    confidence: float | None
    amount_cents: int | None = None
    merchant: str | None = None
    expense_time: datetime | None = None
    category: str | None = None


@dataclass(frozen=True)
class OcrExtraction:
    provider_name: str
    ocr_model: str | None
    result: OcrResult


@dataclass(frozen=True)
class OcrFactSnapshot:
    raw_text: str | None
    parsed_amount_cents: int | None
    parsed_merchant: str | None
    parsed_category: str | None
    parsed_expense_time: datetime | None
    parse_confidence: float | None


class OcrProvider(Protocol):
    def extract(self, expense: Expense, timezone_name: str | None = None) -> OcrResult:
        ...


OCR_DRAFT_FIELDS = frozenset({"amount_cents", "merchant", "category", "expense_time"})
OCR_DRAFT_FIELD_ALIASES = {
    "amount_cents": "amount_cents",
    "home_amount_cents": "amount_cents",
    "original_amount": "amount_cents",
    "original_amount_minor": "amount_cents",
    "original_currency": "amount_cents",
    "original_currency_code": "amount_cents",
    "exchange_rate_to_cny": "amount_cents",
    "exchange_rate_date": "amount_cents",
    "exchange_rate_source": "amount_cents",
    "fx_status": "amount_cents",
    "merchant": "merchant",
    "category": "category",
    "expense_time": "expense_time",
    "spent_at": "expense_time",
}
LEGACY_AUTO_OCR_WINDOW = timedelta(minutes=5)
