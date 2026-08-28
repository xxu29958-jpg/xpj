"""Single DB-owner protocol for publishing one derived expense thumbnail."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Expense
from app.services import thumb_service


def claim_staged_thumbnail(
    expense: Expense,
    staged: thumb_service.StagedThumbnail,
    *,
    replace_missing_reference: bool,
) -> bool:
    """Claim an attempt while the caller holds the Expense row lock.

    Enrichment only fills an empty owner. Lazy GET may replace a durable
    reference whose final bytes never published (for example after commit ACK
    loss), but never replaces an already materialized thumbnail.
    """

    if (
        expense.image_path != staged.source_reference
        or expense.image_deleted_at is not None
        or expense.thumbnail_deleted_at is not None
    ):
        return False
    if expense.thumbnail_path:
        if not replace_missing_reference:
            return False
        if (
            thumb_service.resolve_protected_thumbnail(
                expense.thumbnail_path,
                expense.tenant_id,
            )
            is not None
        ):
            return False
    expense.thumbnail_path = staged.final_reference
    expense.thumbnail_deleted_at = None
    return True


def publish_claimed_thumbnail(
    db: Session,
    expense: Expense,
    staged: thumb_service.StagedThumbnail,
) -> bool:
    """Publish, then prove this attempt still owns the live Expense reference.

    The durable reference is committed by the caller before this function.
    Publication is lock-free; the post-publication row lock serializes the
    ownership proof with cleanup. A losing attempt can delete only its own
    unique final, never another attempt's file.
    """

    thumb_service.publish_staged_thumbnail_attempt(staged)
    db.refresh(expense, with_for_update=True)
    owns_live_reference = (
        expense.image_path == staged.source_reference
        and expense.thumbnail_path == staged.final_reference
        and expense.image_deleted_at is None
        and expense.thumbnail_deleted_at is None
    )
    if owns_live_reference:
        return True
    thumb_service.discard_published_thumbnail_attempt(staged)
    return False
