from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings
from app.models import Expense


@dataclass(frozen=True)
class OcrResult:
    raw_text: str
    confidence: float | None


class OcrProvider(Protocol):
    def extract(self, expense: Expense) -> OcrResult:
        ...


class EmptyOcrProvider:
    def extract(self, expense: Expense) -> OcrResult:
        return OcrResult(raw_text=expense.raw_text or "", confidence=expense.confidence)


class MockOcrProvider:
    def extract(self, expense: Expense) -> OcrResult:
        raw_text = expense.raw_text or "MOCK_OCR_PROVIDER 未接入真实 OCR"
        return OcrResult(raw_text=raw_text, confidence=expense.confidence if expense.confidence is not None else 0.0)


def get_ocr_provider() -> OcrProvider:
    provider_name = get_settings().ocr_provider
    if provider_name == "mock":
        return MockOcrProvider()
    return EmptyOcrProvider()


def retry_ocr(expense: Expense, provider: OcrProvider | None = None) -> Expense:
    active_provider = provider or get_ocr_provider()
    result = active_provider.extract(expense)
    expense.raw_text = result.raw_text
    expense.confidence = result.confidence
    return expense
