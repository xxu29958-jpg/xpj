"""Bridge OCR extraction results into append-only learning facts."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Expense
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.ocr_service import OcrResult, ocr_fact_snapshot


def append_ocr_fact(
    db: Session,
    *,
    expense: Expense,
    result: OcrResult,
    provider_name: str,
    ocr_model: str | None = None,
    timezone_name: str | None = None,
) -> None:
    snapshot = ocr_fact_snapshot(result, timezone_name=timezone_name)
    record_ocr_fact(
        db,
        OcrFactDraft(
            tenant_id=expense.tenant_id,
            expense_id=expense.id,
            ocr_provider=provider_name,
            ocr_model=ocr_model,
            raw_text=snapshot.raw_text,
            parsed_amount_cents=snapshot.parsed_amount_cents,
            parsed_merchant=snapshot.parsed_merchant,
            parsed_category=snapshot.parsed_category,
            parsed_expense_time=snapshot.parsed_expense_time,
            parse_confidence=snapshot.parse_confidence,
        ),
    )
