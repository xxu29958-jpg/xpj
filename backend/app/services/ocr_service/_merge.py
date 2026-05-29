"""Pure helpers for combining raw OCR results with text-only parse fallback."""

from __future__ import annotations

from app.services.category_common import DEFAULT_CATEGORIES, normalize_category
from app.services.ocr_service._models import OcrResult
from app.services.receipt_parse_service import parse_receipt_text


def _merge_result_with_text_parse(
    result: OcrResult,
    *,
    parsed_confidence: float | None,
    timezone_name: str | None = None,
) -> OcrResult:
    parsed = parse_receipt_text(result.raw_text, timezone_name=timezone_name)
    return OcrResult(
        raw_text=result.raw_text,
        confidence=_best_confidence(result.confidence, parsed_confidence, parsed.confidence),
        amount_cents=_positive_amount_cents(result.amount_cents)
        or _positive_amount_cents(parsed.amount_cents),
        merchant=result.merchant or parsed.merchant,
        expense_time=result.expense_time or parsed.expense_time,
        category=_safe_category(result.category) or _safe_category(parsed.category),
    )


def _best_confidence(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(0.0, min(1.0, max(present)))


def _positive_amount_cents(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


def _safe_category(value: str | None) -> str | None:
    normalized = normalize_category(value) if value is not None else None
    return normalized if normalized in DEFAULT_CATEGORIES else None
