"""OCR service: provider pipeline + draft-field bookkeeping + result application.

ADR-0015 pins the 3-layer provider/parse/expense architecture; this package
keeps each layer in its own private sub-module:

- ``_models``: ``OcrResult`` dataclass, ``OcrProvider`` Protocol, draft-field
  constants. Leaf with no app.services deps.
- ``_merge``: pure result + text-parse combiner.
- ``_llm_parsing``: LocalLlmOcrProvider response JSON parsing helpers.
- ``_draft_fields``: ``ocr_draft_fields`` bookkeeping and legacy back-compat.
- ``_providers``: 4 provider implementations + ``get_ocr_provider`` factory.
- ``_apply``: ``extract_ocr_result``/``retry_ocr``/auto-OCR orchestration and
  the canonical ``apply_ocr_result`` that mutates an Expense.

External callers keep importing from ``app.services.ocr_service``; the full
public surface is re-exported below.
"""

from __future__ import annotations

from app.services.ocr_service._apply import (
    apply_ocr_result,
    collect_auto_ocr_extractions,
    collect_auto_ocr_results,
    extract_ocr_result,
    ocr_fact_snapshot,
    retry_ocr,
    run_auto_ocr,
)
from app.services.ocr_service._draft_fields import (
    canonical_ocr_draft_fields,
    clear_ocr_draft_fields,
    ocr_draft_fields,
    ocr_draft_fields_after_clearing,
    serialize_ocr_draft_fields,
)
from app.services.ocr_service._models import (
    LEGACY_AUTO_OCR_WINDOW,
    OCR_DRAFT_FIELD_ALIASES,
    OCR_DRAFT_FIELDS,
    OcrExtraction,
    OcrFactSnapshot,
    OcrProvider,
    OcrResult,
)
from app.services.ocr_service._providers import (
    EmptyOcrProvider,
    LocalLlmOcrProvider,
    MockOcrProvider,
    RapidOcrProvider,
    get_ocr_provider,
)

__all__ = [
    "LEGACY_AUTO_OCR_WINDOW",
    "OCR_DRAFT_FIELDS",
    "OCR_DRAFT_FIELD_ALIASES",
    "EmptyOcrProvider",
    "LocalLlmOcrProvider",
    "MockOcrProvider",
    "OcrProvider",
    "OcrResult",
    "OcrExtraction",
    "OcrFactSnapshot",
    "RapidOcrProvider",
    "apply_ocr_result",
    "canonical_ocr_draft_fields",
    "clear_ocr_draft_fields",
    "collect_auto_ocr_extractions",
    "collect_auto_ocr_results",
    "extract_ocr_result",
    "get_ocr_provider",
    "ocr_fact_snapshot",
    "ocr_draft_fields",
    "ocr_draft_fields_after_clearing",
    "retry_ocr",
    "run_auto_ocr",
    "serialize_ocr_draft_fields",
]
