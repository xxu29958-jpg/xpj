"""Resolve protected image / thumbnail files for an expense."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import thumb_service
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_service._query import get_expense
from app.services.expense_service._thumbnail_publication import (
    claim_staged_thumbnail,
    publish_claimed_thumbnail,
)
from app.services.file_service import resolve_protected_image

__all__ = ["ensure_image_file", "ensure_thumbnail_file"]


def ensure_thumbnail_file(db: Session, expense_id: int, tenant_id: str) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.image_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    if expense.thumbnail_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    resolved = thumb_service.resolve_protected_thumbnail(expense.thumbnail_path, tenant_id)
    if resolved is not None:
        return resolved

    authorize_currency_metadata_write(db)
    thumbnail_source_path = expense.image_path
    staged = thumb_service.stage_thumbnail(thumbnail_source_path, tenant_id=tenant_id)
    if staged is not None:
        try:
            # Rendering is deliberately outside the row lock. Before this
            # staged derivative can become durable truth, serialize with file
            # cleanup and recheck that its source is still the live image.
            db.refresh(expense, with_for_update=True)
            if (
                expense.image_path != thumbnail_source_path
                or expense.image_deleted_at is not None
                or expense.thumbnail_deleted_at is not None
            ):
                raise AppError("image_not_found", status_code=404)
            if claim_staged_thumbnail(
                expense,
                staged,
                replace_missing_reference=True,
            ):
                # The attempt-unique reference is durable before publication.
                # ACK uncertainty leaves no shared final to compensate; a
                # later GET can claim a fresh attempt and self-heal.
                db.commit()
                publish_claimed_thumbnail(db, expense, staged)
        finally:
            thumb_service.discard_staged_thumbnail(staged)

    if expense.image_deleted_at is not None or expense.thumbnail_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    resolved = thumb_service.resolve_protected_thumbnail(expense.thumbnail_path, tenant_id)
    if resolved is None:
        raise AppError("image_not_found", status_code=404)
    return resolved


def ensure_image_file(db: Session, expense_id: int, tenant_id: str) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.image_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    return resolve_protected_image(expense.image_path, tenant_id)
