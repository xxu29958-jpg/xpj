"""expense_service package facade.

The pre-split module exposed 14 public functions plus the
``EDITABLE_STATUSES`` constant; every caller still uses
``from app.services.expense_service import ...`` so this facade re-exports
the full original public surface unchanged.

Internal layout:

- ``_helpers``  — text cleaners, notification key hash, FX gating, thumbnail
                  helper, OCR draft refresh; ``EDITABLE_STATUSES`` lives here
- ``_query``    — ``get_expense``, ``list_pending``, ``list_confirmed``
- ``_create``   — upload pending + enrichment, manual entry, notification draft
- ``_update``   — field update, batch update, confirm, reject
- ``_ocr``      — retry / text re-recognition (with optimistic claim)
- ``_image``    — image / thumbnail file resolution
- ``_duplicate``— suspected-duplicate listing + manual override
"""

from __future__ import annotations

from app.services.expense_service._create import (
    create_manual_expense,
    create_notification_draft,
    create_pending_expense,
    enrich_pending_expense,
)
from app.services.expense_service._duplicate import (
    list_duplicate_expenses,
    mark_expense_not_duplicate,
)
from app.services.expense_service._helpers import (
    EDITABLE_STATUSES,
    NOTIFICATION_DRAFT_SOURCE_PREFIX,
)
from app.services.expense_service._image import ensure_image_file, ensure_thumbnail_file
from app.services.expense_service._ocr import recognize_expense_text, retry_expense_ocr
from app.services.expense_service._query import (
    fetch_expense_row_version_in_status,
    get_expense,
    is_expense_in_status_for_tenant,
    ledger_has_any_expense,
    list_confirmed,
    list_expenses_by_ids,
    list_pending,
    resolve_expense,
)
from app.services.expense_service._update import (
    batch_update_confirmed_expenses,
    confirm_expense,
    reject_expense,
    undo_reject_expense,
    update_expense,
)

__all__ = [
    "EDITABLE_STATUSES",
    "NOTIFICATION_DRAFT_SOURCE_PREFIX",
    "batch_update_confirmed_expenses",
    "confirm_expense",
    "create_manual_expense",
    "create_notification_draft",
    "create_pending_expense",
    "ensure_image_file",
    "ensure_thumbnail_file",
    "enrich_pending_expense",
    "fetch_expense_row_version_in_status",
    "get_expense",
    "is_expense_in_status_for_tenant",
    "ledger_has_any_expense",
    "list_confirmed",
    "list_duplicate_expenses",
    "list_expenses_by_ids",
    "list_pending",
    "mark_expense_not_duplicate",
    "recognize_expense_text",
    "reject_expense",
    "resolve_expense",
    "retry_expense_ocr",
    "undo_reject_expense",
    "update_expense",
]
