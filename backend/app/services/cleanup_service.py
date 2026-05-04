from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, get_settings
from app.models import Expense
from app.services.time_service import now_utc


@dataclass(frozen=True)
class CleanupResult:
    enabled: bool
    delete_after_days: int
    scanned: int
    deleted_images: int
    deleted_thumbnails: int


def _delete_relative_file(relative_path: str | None) -> bool:
    if not relative_path:
        return False
    settings = get_settings()
    candidate = (BACKEND_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(settings.upload_dir)
    except ValueError:
        return False
    if candidate.is_file():
        candidate.unlink()
        return True
    return False


def cleanup_after_confirm(expense: Expense) -> Expense:
    settings = get_settings()
    if not settings.delete_image_after_confirm:
        return expense

    now = now_utc()
    if _delete_relative_file(expense.image_path):
        expense.image_deleted_at = now
    return expense


def cleanup_confirmed_images(db: Session) -> CleanupResult:
    settings = get_settings()
    if settings.delete_image_after_days <= 0:
        return CleanupResult(
            enabled=False,
            delete_after_days=settings.delete_image_after_days,
            scanned=0,
            deleted_images=0,
            deleted_thumbnails=0,
        )

    cutoff = now_utc() - timedelta(days=settings.delete_image_after_days)
    expenses = list(
        db.scalars(
            select(Expense).where(
                Expense.status == "confirmed",
                Expense.confirmed_at.is_not(None),
                Expense.confirmed_at <= cutoff,
            ),
        ),
    )

    now = now_utc()
    deleted_images = 0
    deleted_thumbnails = 0
    for expense in expenses:
        changed = False
        if expense.image_deleted_at is None and _delete_relative_file(expense.image_path):
            expense.image_deleted_at = now
            deleted_images += 1
            changed = True
        if expense.thumbnail_deleted_at is None and _delete_relative_file(expense.thumbnail_path):
            expense.thumbnail_deleted_at = now
            deleted_thumbnails += 1
            changed = True
        if changed:
            expense.updated_at = now

    if deleted_images or deleted_thumbnails:
        db.commit()

    return CleanupResult(
        enabled=True,
        delete_after_days=settings.delete_image_after_days,
        scanned=len(expenses),
        deleted_images=deleted_images,
        deleted_thumbnails=deleted_thumbnails,
    )
