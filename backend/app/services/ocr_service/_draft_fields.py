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


def ocr_draft_fields(
    expense: Expense,
    *,
    effective_row_version: int | None = None,
    allow_legacy_ocr_only: bool = False,
) -> set[str]:
    payload = expense.ocr_draft_fields
    if not payload:
        return _legacy_pending_ocr_draft_fields(
            expense,
            effective_row_version=effective_row_version,
            allow_legacy_ocr_only=allow_legacy_ocr_only,
        )
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


def is_within_legacy_auto_ocr_window(expense: Expense) -> bool:
    created_at = ensure_utc(expense.created_at)
    updated_at = ensure_utc(expense.updated_at)
    if created_at is None or updated_at is None:
        return False
    return updated_at - created_at <= LEGACY_AUTO_OCR_WINDOW


def _starting_draft_fields_for_clearing(
    expense: Expense,
    *,
    effective_row_version: int | None = None,
    initial_untouched: set[str] | None = None,
    allow_legacy_ocr_only: bool = False,
    allow_legacy_untouched: bool = False,
) -> set[str]:
    current = ocr_draft_fields(
        expense,
        effective_row_version=effective_row_version,
        allow_legacy_ocr_only=allow_legacy_ocr_only,
    )
    if allow_legacy_untouched:
        current |= untouched_ocr_draft_fields(expense) if initial_untouched is None else set(initial_untouched)
    elif (
        expense.ocr_draft_fields is None
        and (expense.source or "") != "手动记账"
        and (expense.confidence is None or is_within_legacy_auto_ocr_window(expense))
    ):
        eff_ver = expense.row_version if effective_row_version is None else effective_row_version
        if eff_ver is None or eff_ver <= 1:
            current |= untouched_ocr_draft_fields(expense) if initial_untouched is None else set(initial_untouched)
    return current


def ocr_draft_fields_after_clearing(
    expense: Expense,
    fields: set[str] | list[str] | tuple[str, ...],
    *,
    effective_row_version: int | None = None,
    initial_untouched: set[str] | None = None,
    allow_legacy_ocr_only: bool = False,
    allow_legacy_untouched: bool = False,
) -> str:
    current = _starting_draft_fields_for_clearing(
        expense,
        effective_row_version=effective_row_version,
        initial_untouched=initial_untouched,
        allow_legacy_ocr_only=allow_legacy_ocr_only,
        allow_legacy_untouched=allow_legacy_untouched,
    )
    updated = current.difference(canonical_ocr_draft_fields(fields))
    return serialize_ocr_draft_fields(list(updated))


def clear_ocr_draft_fields(
    expense: Expense,
    fields: set[str] | list[str] | tuple[str, ...],
    *,
    effective_row_version: int | None = None,
    initial_untouched: set[str] | None = None,
    allow_legacy_ocr_only: bool = False,
    allow_legacy_untouched: bool = False,
) -> None:
    current = _starting_draft_fields_for_clearing(
        expense,
        effective_row_version=effective_row_version,
        initial_untouched=initial_untouched,
        allow_legacy_ocr_only=allow_legacy_ocr_only,
        allow_legacy_untouched=allow_legacy_untouched,
    )
    updated = current.difference(canonical_ocr_draft_fields(fields))
    _write_ocr_draft_fields(expense, updated)


def untouched_ocr_draft_fields(expense: Expense) -> set[str]:
    """Empty/default draft fields on a pre-tracking row that has not been edited."""
    fields: set[str] = set()
    if expense.amount_cents is None:
        fields.add("amount_cents")
    if not (expense.merchant or "").strip():
        fields.add("merchant")
    if normalize_category(expense.category) == "其他":
        fields.add("category")
    if expense.expense_time is None and expense.time_precision != "date_only":
        fields.add("expense_time")
    return fields


def can_apply_ocr_field(
    expense: Expense,
    field: str,
    draft_fields: set[str] | None = None,
    *,
    is_empty_or_default: bool,
    effective_row_version: int | None = None,
    allow_legacy_ocr_only: bool = False,
    allow_legacy_untouched: bool = False,
) -> bool:
    """Whether OCR or auto-classification may write ``field`` on ``expense``.

    When ``expense.ocr_draft_fields`` is persisted (not ``None``), it is the
    authoritative allow-list of fields still owned by OCR/defaults: a field
    absent from it was explicitly saved or cleared by the user and must not
    be overwritten even if its value is empty or ``其他`` unless verifiable
    provenance proves no human edits ever occurred on a pre-upgrade partial
    list (``allow_legacy_untouched=True``). When the column is ``None``,
    check pre-claim ``row_version`` BEFORE inferring populated fields so
    manual edits within the 5-minute window cannot be overwritten.
    """
    eff_ver = expense.row_version if effective_row_version is None else effective_row_version
    if expense.ocr_draft_fields is None and eff_ver is not None and eff_ver > 1 and not allow_legacy_ocr_only:
        return False
    resolved = (
        ocr_draft_fields(
            expense,
            effective_row_version=eff_ver,
            allow_legacy_ocr_only=allow_legacy_ocr_only,
        )
        if draft_fields is None
        else draft_fields
    )
    if field in resolved:
        return True
    if expense.ocr_draft_fields is not None:
        return bool(allow_legacy_untouched and is_empty_or_default)
    if expense.confidence is not None and not allow_legacy_ocr_only:
        created_at = ensure_utc(expense.created_at)
        updated_at = ensure_utc(expense.updated_at)
        if created_at is not None and updated_at is not None and updated_at - created_at > LEGACY_AUTO_OCR_WINDOW:
            return False
    return is_empty_or_default


def _legacy_pending_ocr_draft_fields(
    expense: Expense,
    *,
    effective_row_version: int | None = None,
    allow_legacy_ocr_only: bool = False,
) -> set[str]:
    if expense.status != "pending":
        return set()
    eff_ver = expense.row_version if effective_row_version is None else effective_row_version
    if eff_ver is not None and eff_ver > 1 and not allow_legacy_ocr_only:
        return set()
    # v1.2 OCR single-source migration (step 5): the legacy gate
    # used to require non-empty ``expense.raw_text`` *and* a non-null
    # confidence. Confidence alone is the more reliable "OCR ran"
    # signal — ``apply_ocr_result`` sets it on every successful pass
    # and was already the second half of the original AND. Dropping
    # the raw_text check lets us stay off the deprecated column
    # without losing legacy-row detection for any expense that has
    # been OCR'd.
    if expense.confidence is None:
        return set()
    if not allow_legacy_ocr_only:
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
