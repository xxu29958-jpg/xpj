"""Data Quality insights — read-only aggregation over Expense rows.

v0.4-alpha3 slice 2 / M4. The data-quality dashboard exposes a single
summary endpoint that the /web page and (later) Android can consume.
All metrics are read-only counters scoped by ``tenant_id``.

Metric definitions:
- ``pending_total``: rows with ``status = 'pending'``
- ``missing_amount``: pending rows with ``amount_cents IS NULL``
- ``missing_merchant``: pending rows with empty / whitespace merchant
- ``missing_category``: pending or confirmed rows with empty / NULL /
  ``'未分类'`` category — these are the rows that defeat stats slicing
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
- ``ready_to_confirm``: pending rows with amount + merchant + non-duplicate
- ``ready_to_confirm_categorized``: ``ready_to_confirm`` rows that also have
  a real category — the caliber the Android inbox "ready to confirm" filter
  lands on (its quick-category step takes precedence over confirm for
  uncategorized rows, so the mixed ``ready_to_confirm`` count would send
  users to a shorter list than advertised)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.fx_constants import FX_STATUS_READY
from app.models import Expense

_UNCATEGORIZED_TOKENS = {"", "未分类", "未分類", "none", "null"}


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


def _ready_to_confirm_stmt(base, *, empty_merchant):
    """Pending rows with amount + merchant + fx-ready + non-duplicate."""
    return (
        base.where(Expense.status == "pending")
        .where(Expense.amount_cents.is_not(None))
        .where(Expense.fx_status == FX_STATUS_READY)
        .where(~empty_merchant)
        .where(Expense.duplicate_status != "suspected")
    )


def _missing_category_parts(db: Session, base, *, uncategorized) -> tuple[int, int]:
    """Split the uncategorized count by status (pending → inbox, confirmed → ledger)."""
    pending = _count(db, base.where(Expense.status == "pending").where(uncategorized))
    confirmed = _count(db, base.where(Expense.status == "confirmed").where(uncategorized))
    return pending, confirmed


def data_quality_summary(db: Session, *, tenant_id: str) -> DataQualitySummary:
    """Return a single DataQualitySummary for the given tenant."""
    base = select(func.count(Expense.id)).where(Expense.tenant_id == tenant_id)

    pending_total = _count(db, base.where(Expense.status == "pending"))

    missing_amount = _count(
        db,
        base.where(Expense.status == "pending").where(Expense.amount_cents.is_(None)),
    )

    empty_merchant = or_(
        Expense.merchant.is_(None),
        func.trim(Expense.merchant) == "",
    )
    missing_merchant = _count(
        db,
        base.where(Expense.status == "pending").where(empty_merchant),
    )

    uncategorized = or_(
        Expense.category.is_(None),
        func.trim(Expense.category) == "",
        Expense.category == "未分类",
        Expense.category == "未分類",
    )
    missing_category_pending, missing_category_confirmed = _missing_category_parts(
        db, base, uncategorized=uncategorized
    )
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

    ready_to_confirm = _count(db, _ready_to_confirm_stmt(base, empty_merchant=empty_merchant))

    ready_to_confirm_categorized = _count(
        db,
        _ready_to_confirm_stmt(base, empty_merchant=empty_merchant).where(~uncategorized),
    )

    oldest_dt = db.scalar(
        select(func.min(Expense.created_at))
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "pending")
    )
    oldest_pending_age_days: int | None
    if oldest_dt is None:
        oldest_pending_age_days = None
    else:
        oldest_dt_aware = oldest_dt.replace(tzinfo=UTC) if oldest_dt.tzinfo is None else oldest_dt
        delta = datetime.now(tz=UTC) - oldest_dt_aware
        oldest_pending_age_days = max(0, int(delta.total_seconds() // 86400))

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
