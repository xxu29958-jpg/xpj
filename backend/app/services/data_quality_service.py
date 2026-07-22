"""Data Quality insights — read-only aggregation over Expense rows.

v0.4-alpha3 slice 2 / M4. The data-quality dashboard exposes a single
summary endpoint that the /web page and (later) Android can consume.
All metrics are read-only counters scoped by ``tenant_id``.

Metric definitions:
- ``pending_total``: rows with ``status = 'pending'``
- ``missing_amount``: pending rows with ``amount_cents IS NULL``
- ``missing_merchant``: pending rows whose merchant is UNUSABLE per the
  inbox caliber ported from Android ``pendingMerchantPresentation``:
  NULL/blank, fewer than two letter-or-digit characters, no letter at all,
  or a pure OCR time/date noise string
- ``missing_category``: pending or confirmed rows whose category is empty /
  NULL / an uncategorized token (``'未分类'``, ``'未分類'``, ``'none'``,
  ``'null'`` — after trim + lowercase, ported from Android
  ``isUncategorizedExpenseCategory``) — these are the rows that defeat
  stats slicing
- ``missing_category_pending`` / ``missing_category_confirmed``: the
  ``missing_category`` total split by status. Clients route the two parts
  to different remediation surfaces (pending → inbox, confirmed → ledger),
  so they need the composition, not just the mixed total
  (``missing_category == missing_category_pending + missing_category_confirmed``)
- ``suspected_duplicates``: pending rows with ``duplicate_status = 'suspected'``
- ``confirmed_without_image``: confirmed rows whose image was deleted by
  retention OR was never uploaded — affects auditability
- ``oldest_pending_age_days``: days since the oldest pending row was
  ingested, ``None`` if none pending
- ``ready_to_confirm``: pending rows with amount + usable merchant +
  fx-ready + non-duplicate (merchant usability per the same ported caliber)
- ``ready_to_confirm_categorized``: ``ready_to_confirm`` rows that also have
  a real category — exactly the Android inbox "ready to confirm" filter
  caliber (its quick-category step takes precedence over confirm for
  uncategorized rows, so the mixed ``ready_to_confirm`` count would send
  users to a shorter list than advertised)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.fx_constants import FX_STATUS_READY
from app.models import Expense

_UNCATEGORIZED_TOKENS = {"", "未分类", "未分類", "none", "null"}

# ── Ported Android calibers ──────────────────────────────────────────────
# The data-quality counters must land on exactly the rows the Android inbox
# filters show, so the merchant-usability and category-token rules below are
# line-for-line ports of `PendingScreenModels.kt` (pendingMerchantPresentation)
# and `DefaultCategories.kt` (isUncategorizedExpenseCategory). Keep the two
# sides in sync — shared sample sets in tests/test_data_quality_caliber_port.py
# and PendingScreenModelsTest.kt / DefaultCategoriesTest.kt pin the equivalence.

# Kotlin String.trim() strips Java whitespace + space chars: the ISO control
# separators plus every Unicode Zs/Zl/Zp code point. Python str.strip() also
# strips e.g. U+0085, so trim against this explicit set instead.
_KOTLIN_TRIM_CHARS = "".join(
    chr(cp) for cp in (
        # Java whitespace control chars, then every Unicode Zs/Zl/Zp
        # code point — written as code points so no invisible literals
        # land in source.
        0x20, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x1F,
        0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
    )
)

# Same patterns and flags as PendingTimeNoise / PendingDateNoise. re.ASCII
# pins \s and \d to the JVM default (ASCII-only; Python str patterns would
# otherwise match Unicode whitespace/digits).
_PENDING_TIME_NOISE = re.compile(
    r"^\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?(?:\s*[AP]M)?$",
    re.IGNORECASE | re.ASCII,
)
_PENDING_DATE_NOISE = re.compile(
    r"^(?:\d{4}\s*[-/.年]\s*)?\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?"
    r"(?:\s+周[一二三四五六日天])?(?:\s+\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?)?$",
    re.IGNORECASE | re.ASCII,
)


def _utf16_units(value: str):
    """Yield the string as Kotlin Char (UTF-16 code units) — a supplementary
    code point is TWO units (neither a letter), matching the Android counts."""
    data = value.encode("utf-16-le", errors="surrogatepass")
    for i in range(0, len(data), 2):
        yield chr(data[i] | (data[i + 1] << 8))


def _is_kotlin_letter(ch: str) -> bool:
    # Kotlin Char.isLetter(): Unicode general category L*.
    return unicodedata.category(ch).startswith("L")


def _is_kotlin_letter_or_digit(ch: str) -> bool:
    # Kotlin Char.isLetterOrDigit(): Unicode general category L* or Nd.
    category = unicodedata.category(ch)
    return category.startswith("L") or category == "Nd"


def is_usable_pending_merchant(value: str | None) -> bool:
    """Port of Android ``pendingMerchantPresentation``: the negation of its
    ``needsReview`` — trim, then require >= 2 letter-or-digit chars, >= 1
    letter, and neither the time- nor the date-noise pattern."""
    if value is None:
        return False
    trimmed = value.strip(_KOTLIN_TRIM_CHARS)
    units = list(_utf16_units(trimmed))
    meaningful_character_count = sum(1 for ch in units if _is_kotlin_letter_or_digit(ch))
    merchant_letter_count = sum(1 for ch in units if _is_kotlin_letter(ch))
    return (
        meaningful_character_count >= 2
        and merchant_letter_count >= 1
        and not _PENDING_TIME_NOISE.match(trimmed)
        and not _PENDING_DATE_NOISE.match(trimmed)
    )


def is_uncategorized_expense_category(value: str | None) -> bool:
    """Port of Android ``isUncategorizedExpenseCategory``: trim → lowercase →
    membership in the uncategorized token set (None behaves like Android's
    ``?.`` chain: it falls through to the empty token)."""
    if value is None:
        return True
    return value.strip(_KOTLIN_TRIM_CHARS).lower() in _UNCATEGORIZED_TOKENS


@dataclass(frozen=True)
class DataQualitySummary:
    pending_total: int
    missing_amount: int
    missing_merchant: int
    missing_category: int
    missing_category_pending: int
    missing_category_confirmed: int
    suspected_duplicates: int
    confirmed_without_image: int
    ready_to_confirm: int
    ready_to_confirm_categorized: int
    oldest_pending_age_days: int | None
    generated_at: datetime

    def to_dict(self) -> dict:
        return {
            "pending_total": self.pending_total,
            "missing_amount": self.missing_amount,
            "missing_merchant": self.missing_merchant,
            "missing_category": self.missing_category,
            "missing_category_pending": self.missing_category_pending,
            "missing_category_confirmed": self.missing_category_confirmed,
            "suspected_duplicates": self.suspected_duplicates,
            "confirmed_without_image": self.confirmed_without_image,
            "ready_to_confirm": self.ready_to_confirm,
            "ready_to_confirm_categorized": self.ready_to_confirm_categorized,
            "oldest_pending_age_days": self.oldest_pending_age_days,
            "generated_at": self.generated_at.isoformat(),
        }


def _count(db: Session, stmt) -> int:
    result = db.scalar(stmt)
    return int(result or 0)


def _count_grouped(db: Session, stmt, predicate) -> int:
    """Sum a GROUP BY row-count over the groups whose key passes ``predicate``.

    The ported usability rules inspect Unicode categories and OCR-noise
    patterns — not faithfully expressible in SQL — so evaluate them
    Python-side over grouped keys. Traffic stays proportional to the number
    of distinct merchant/category values, not to the number of rows.
    """
    total = 0
    for row in db.execute(stmt):
        *keys, n = row
        if predicate(*keys):
            total += int(n)
    return total


def _ready_to_confirm_filters() -> tuple:
    """SQL-expressible part of the ready caliber: pending + amount + fx-ready
    + non-duplicate (merchant/category calibers are applied Python-side).

    The tenant predicate is deliberately NOT in here: each call site adds it
    inline so the ledger-scope guard (tests/test_ledger_query_scope_guard.py,
    per-statement AST walk) sees an explicit ``Expense.tenant_id`` comparison
    inside the query statement itself."""
    return (
        Expense.status == "pending",
        Expense.amount_cents.is_not(None),
        Expense.fx_status == FX_STATUS_READY,
        Expense.duplicate_status != "suspected",
    )


def _missing_category_part(db: Session, *, tenant_id: str, status: str) -> int:
    """Uncategorized rows for one status (pending → inbox, confirmed → ledger)."""
    return _count_grouped(
        db,
        select(Expense.category, func.count())
        .where(Expense.tenant_id == tenant_id, Expense.status == status)
        .group_by(Expense.category),
        is_uncategorized_expense_category,
    )


def _oldest_pending_age_days(db: Session, *, tenant_id: str) -> int | None:
    """Days since the oldest pending row was ingested, ``None`` if none pending."""
    oldest_dt = db.scalar(
        select(func.min(Expense.created_at))
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "pending")
    )
    if oldest_dt is None:
        return None
    oldest_dt_aware = oldest_dt.replace(tzinfo=UTC) if oldest_dt.tzinfo is None else oldest_dt
    delta = datetime.now(tz=UTC) - oldest_dt_aware
    return max(0, int(delta.total_seconds() // 86400))


def data_quality_summary(db: Session, *, tenant_id: str) -> DataQualitySummary:
    """Return a single DataQualitySummary for the given tenant."""
    base = select(func.count(Expense.id)).where(Expense.tenant_id == tenant_id)

    pending_total = _count(db, base.where(Expense.status == "pending"))

    missing_amount = _count(
        db,
        base.where(Expense.status == "pending").where(Expense.amount_cents.is_(None)),
    )

    missing_merchant = _count_grouped(
        db,
        select(Expense.merchant, func.count())
        .where(Expense.tenant_id == tenant_id, Expense.status == "pending")
        .group_by(Expense.merchant),
        lambda merchant: not is_usable_pending_merchant(merchant),
    )

    missing_category_pending = _missing_category_part(db, tenant_id=tenant_id, status="pending")
    missing_category_confirmed = _missing_category_part(db, tenant_id=tenant_id, status="confirmed")
    missing_category = missing_category_pending + missing_category_confirmed

    suspected_duplicates = _count(
        db,
        base.where(Expense.status == "pending").where(Expense.duplicate_status == "suspected"),
    )

    confirmed_without_image = _count(
        db,
        base.where(Expense.status == "confirmed").where(
            or_(Expense.image_path.is_(None), Expense.image_deleted_at.is_not(None))
        ),
    )

    ready_filters = _ready_to_confirm_filters()
    ready_to_confirm = _count_grouped(
        db,
        select(Expense.merchant, func.count())
        .where(Expense.tenant_id == tenant_id, *ready_filters)
        .group_by(Expense.merchant),
        is_usable_pending_merchant,
    )
    ready_to_confirm_categorized = _count_grouped(
        db,
        select(Expense.merchant, Expense.category, func.count())
        .where(Expense.tenant_id == tenant_id, *ready_filters)
        .group_by(Expense.merchant, Expense.category),
        lambda merchant, category: (
            is_usable_pending_merchant(merchant)
            and not is_uncategorized_expense_category(category)
        ),
    )

    oldest_pending_age_days = _oldest_pending_age_days(db, tenant_id=tenant_id)

    return DataQualitySummary(
        pending_total=pending_total,
        missing_amount=missing_amount,
        missing_merchant=missing_merchant,
        missing_category=missing_category,
        missing_category_pending=missing_category_pending,
        missing_category_confirmed=missing_category_confirmed,
        suspected_duplicates=suspected_duplicates,
        confirmed_without_image=confirmed_without_image,
        ready_to_confirm=ready_to_confirm,
        ready_to_confirm_categorized=ready_to_confirm_categorized,
        oldest_pending_age_days=oldest_pending_age_days,
        generated_at=datetime.now(tz=UTC),
    )
