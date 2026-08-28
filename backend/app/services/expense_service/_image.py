"""Resolve protected image / thumbnail files for an expense."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import thumb_service
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_service._query import get_expense
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
    staged = thumb_service.stage_thumbnail(expense.image_path, tenant_id=tenant_id)
    if staged is not None:
        try:
            # The derived cache locator is durable before file publication. If
            # commit or its acknowledgement fails, only the unique staging file
            # is discarded; a later GET rebuilds the deterministic canonical.
            # Cache materialization never changes the business OCC snapshot.
            expense.thumbnail_path = staged.canonical_reference
            expense.thumbnail_deleted_at = None
            db.commit()
            thumb_service.publish_staged_thumbnail(staged)
        finally:
            thumb_service.discard_staged_thumbnail(staged)

    resolved = thumb_service.resolve_protected_thumbnail(expense.thumbnail_path, tenant_id)
    if resolved is None:
        raise AppError("image_not_found", status_code=404)
    return resolved


def ensure_image_file(db: Session, expense_id: int, tenant_id: str) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.image_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    return resolve_protected_image(expense.image_path, tenant_id)
