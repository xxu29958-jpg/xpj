"""Resolve protected image / thumbnail files for an expense."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services.file_service import resolve_protected_image
from app.services.expense_service._query import get_expense
from app.services.thumb_service import generate_thumbnail, resolve_protected_thumbnail
from app.services.time_service import now_utc


__all__ = ["ensure_image_file", "ensure_thumbnail_file"]


def ensure_thumbnail_file(
    db: Session, expense_id: int, tenant_id: str
) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.image_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    if expense.thumbnail_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    resolved = resolve_protected_thumbnail(expense.thumbnail_path, tenant_id)
    if resolved is not None:
        return resolved

    thumbnail_path = generate_thumbnail(expense.image_path, tenant_id=tenant_id)
    if thumbnail_path is not None:
        expense.thumbnail_path = thumbnail_path
        expense.thumbnail_deleted_at = None
        expense.updated_at = now_utc()
        db.commit()
        db.refresh(expense)

    resolved = resolve_protected_thumbnail(expense.thumbnail_path, tenant_id)
    if resolved is None:
        raise AppError("image_not_found", status_code=404)
    return resolved


def ensure_image_file(
    db: Session, expense_id: int, tenant_id: str
) -> tuple[Path, str]:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.image_deleted_at is not None:
        raise AppError("image_not_found", status_code=404)
    return resolve_protected_image(expense.image_path, tenant_id)
