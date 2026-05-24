"""Pure helpers for combining raw OCR results with text-only parse fallback."""

from __future__ import annotations

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
        amount_cents=result.amount_cents if result.amount_cents is not None else parsed.amount_cents,
        merchant=result.merchant or parsed.merchant,
        expense_time=result.expense_time or parsed.expense_time,
        category=result.category or parsed.category,
    )


def _best_confidence(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(0.0, min(1.0, max(present)))
