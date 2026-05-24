"""ocr_draft_fields read/write + legacy back-compat (leaf)."""

from __future__ import annotations

import json

from app.models import Expense
from app.services.category_service import normalize_category
from app.services.ocr_service._models import (
    LEGACY_AUTO_OCR_WINDOW,
    OCR_DRAFT_FIELD_ALIASES,
    OCR_DRAFT_FIELDS,
)
from app.services.time_service import ensure_utc


def ocr_draft_fields(expense: Expense) -> set[str]:
    payload = expense.ocr_draft_fields
    if not payload:
        return _legacy_pending_ocr_draft_fields(expense)
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return set()
    if not isinstance(decoded, list):
        return set()
    return canonical_ocr_draft_fields([str(item) for item in decoded])


def canonical_ocr_draft_fields(fields: set[str] | list[str] | tuple[str, ...]) -> set[str]:
    return {
        mapped
        for field in fields
        if (mapped := OCR_DRAFT_FIELD_ALIASES.get(str(field))) in OCR_DRAFT_FIELDS
    }


def serialize_ocr_draft_fields(fields: set[str] | list[str] | tuple[str, ...]) -> str:
    normalized = sorted(canonical_ocr_draft_fields(fields))
    return json.dumps(normalized, ensure_ascii=False)


def ocr_draft_fields_after_clearing(
    expense: Expense,
    fields: set[str] | list[str] | tuple[str, ...],
) -> str:
    current = ocr_draft_fields(expense)
    updated = current.difference(canonical_ocr_draft_fields(fields))
    return serialize_ocr_draft_fields(list(updated))


def clear_ocr_draft_fields(expense: Expense, fields: set[str] | list[str] | tuple[str, ...]) -> None:
    updated = ocr_draft_fields(expense).difference(canonical_ocr_draft_fields(fields))
    _write_ocr_draft_fields(expense, updated)


def _legacy_pending_ocr_draft_fields(expense: Expense) -> set[str]:
    if expense.status != "pending":
        return set()
    if not (expense.raw_text or "").strip() or expense.confidence is None:
        return set()
    created_at = ensure_utc(expense.created_at)
    updated_at = ensure_utc(expense.updated_at)
    if created_at is None or updated_at is None:
        return set()
    if updated_at - created_at > LEGACY_AUTO_OCR_WINDOW:
        return set()

    fields: set[str] = set()
    if expense.amount_cents is not None:
        fields.add("amount_cents")
    if (expense.merchant or "").strip():
        fields.add("merchant")
    if normalize_category(expense.category) != "其他":
        fields.add("category")
    if expense.expense_time is not None:
        fields.add("expense_time")
    return fields


def _write_ocr_draft_fields(expense: Expense, fields: set[str]) -> None:
    expense.ocr_draft_fields = serialize_ocr_draft_fields(list(fields))
