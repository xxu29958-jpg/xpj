"""Shared private utilities for the expense_service package.

Symbol layout in this module is dictated by where it gets used:

- ``_clean_*`` helpers normalize untrusted text from create/update payloads.
- ``_notification_*`` helpers compute the dedup key for notification drafts.
- ``_try_generate_thumbnail`` and ``_replace_ocr_draft_items_from_text`` are
  infrastructure leaks shared between create / OCR / enrichment flows.
- ``_expense_has_pending_fx`` / ``_ensure_expense_can_confirm`` keep the
  FX-gating rules in one place so create / update / OCR confirm see the
  same definition. Optimistic-concurrency / ``updated_at`` predicates
  live in :mod:`app.services.optimistic_concurrency`.

``EDITABLE_STATUSES`` is re-exported through the package facade — both
``expense_split_service`` and ``receipt_item_service`` import it directly
from ``app.services.expense_service``.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_STATUS_PENDING
from app.models import Expense
from app.schemas import NotificationDraftCreateRequest
from app.services.category_service import normalize_category
from app.services.expense_query import EDITABLE_STATUSES  # re-exported
from app.services.ocr_service import serialize_ocr_draft_fields
from app.services.receipt_parse_service import parse_receipt_text
from app.services.thumb_service import generate_thumbnail
from app.services.time_service import ensure_utc

_ = EDITABLE_STATUSES  # quiet F401: re-exported through the package facade

__all__ = [
    "EDITABLE_STATUSES",
    "NOTIFICATION_DRAFT_SOURCE_LABELS",
    "NOTIFICATION_DRAFT_SOURCE_PREFIX",
    "NOTIFICATION_DRAFT_WINDOW_MINUTES",
    "logger",
    "background_failure_counts",
    "_clean_category",
    "_clean_notification_source",
    "_clean_optional_text",
    "_clean_text",
    "_ensure_expense_can_confirm",
    "_expense_has_pending_fx",
    "_notification_draft_fields",
    "_notification_draft_key",
    "_notification_window_key",
    "_replace_ocr_draft_items_from_text",
    "_record_background_failure",
    "_try_generate_thumbnail",
]


logger = logging.getLogger(__name__)


# Background tasks (thumbnail generation, auto-OCR enrichment) intentionally
# swallow exceptions so a failure doesn't fail the user-facing upload. The
# counters below give those silent failures a visible surface so health
# checks / future metrics exporters can see them.
_background_failure_counts: dict[str, int] = {}


def background_failure_counts() -> dict[str, int]:
    """Snapshot of in-process background-task failure counters."""
    return dict(_background_failure_counts)


def _record_background_failure(kind: str) -> None:
    _background_failure_counts[kind] = _background_failure_counts.get(kind, 0) + 1


NOTIFICATION_DRAFT_WINDOW_MINUTES = 30
NOTIFICATION_DRAFT_SOURCE_LABELS = {
    "wechat": "微信",
    "alipay": "支付宝",
    "bank_sms": "银行短信",
    "bank_app": "银行 App",
    "other": "其他通知",
}
#: ``Expense.source`` prefix for notification drafts (full stored value =
#: this prefix + NOTIFICATION_DRAFT_SOURCE_LABELS[channel]). Single source
#: of truth shared by the create path and /web source-label matching.
NOTIFICATION_DRAFT_SOURCE_PREFIX = "通知草稿:"


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def _clean_category(value: str | None) -> str:
    return normalize_category(value)


def _clean_notification_source(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_")
    if cleaned not in NOTIFICATION_DRAFT_SOURCE_LABELS:
        raise AppError("notification_source_invalid", status_code=422)
    return cleaned


def _notification_window_key(expense_time, *, fallback_now) -> str:
    when = ensure_utc(expense_time or fallback_now)
    minute = (when.minute // NOTIFICATION_DRAFT_WINDOW_MINUTES) * NOTIFICATION_DRAFT_WINDOW_MINUTES
    bucket = when.replace(minute=minute, second=0, microsecond=0)
    return bucket.isoformat()


def _notification_draft_key(
    *,
    source: str,
    merchant: str | None,
    amount_cents: int | None,
    original_currency: str | None,
    original_amount: object | None,
    expense_time,
    now,
) -> str:
    merchant_key = _clean_optional_text(merchant) or ""
    material = "|".join(
        [
            "notification",
            source,
            merchant_key.casefold(),
            str(amount_cents) if amount_cents is not None else "",
            (original_currency or "").strip().upper(),
            str(original_amount) if original_amount is not None else "",
            _notification_window_key(expense_time, fallback_now=now),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _notification_draft_fields(payload: NotificationDraftCreateRequest) -> str | None:
    fields: set[str] = set()
    if payload.amount_cents is not None:
        fields.add("amount_cents")
    if payload.original_amount is not None or payload.original_amount_minor is not None:
        fields.add("original_amount")
    if payload.original_currency or payload.original_currency_code:
        fields.add("original_currency")
    if _clean_optional_text(payload.merchant):
        fields.add("merchant")
    if payload.expense_time is not None or payload.spent_at is not None:
        fields.add("expense_time")
    if _clean_optional_text(payload.category):
        fields.add("category")
    if not fields:
        return None
    return serialize_ocr_draft_fields(list(fields))


def _try_generate_thumbnail(relative_path: str | None, tenant_id: str) -> str | None:
    try:
        return generate_thumbnail(relative_path, tenant_id=tenant_id)
    except Exception:
        # Thumbnail is an optional artifact — never block the surrounding
        # upload / enrichment on it. The failure is still recorded so
        # health checks can see "thumbnails are silently failing".
        _record_background_failure("thumbnail")
        logger.exception(
            "thumbnail generation failed for ledger=%s path=%s",
            tenant_id,
            relative_path,
        )
        return None


def _expense_has_pending_fx(expense: Expense) -> bool:
    return expense.fx_status == FX_STATUS_PENDING or (
        expense.amount_cents is None and expense.original_amount_minor is not None
    )


def _ensure_expense_can_confirm(expense: Expense) -> None:
    if _expense_has_pending_fx(expense):
        raise AppError("exchange_rate_pending", status_code=409)
    if expense.amount_cents is None:
        raise AppError("amount_required", status_code=400)


def _replace_ocr_draft_items_from_text(
    db: Session,
    expense: Expense,
    raw_text: str,
    *,
    timezone_name: str | None = None,
) -> None:
    if expense.status != "pending":
        return
    parsed = parse_receipt_text(raw_text, timezone_name=timezone_name)
    # Top-level import would form a cycle with receipt_item_service if
    # that module ever re-introduced an expense_service dependency. It
    # currently imports from expense_query only, so this stays local
    # purely as a guard rail.
    from app.services.receipt_item_service import replace_ocr_draft_items

    replace_ocr_draft_items(db, expense, parsed.items)
