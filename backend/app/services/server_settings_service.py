from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Expense


def _upload_storage_bytes() -> int:
    settings = get_settings()
    total = 0
    for path in settings.upload_dir.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _count_expenses(db: Session, *, status: str | None = None, duplicate_status: str | None = None) -> int:
    statement = select(func.count()).select_from(Expense)
    if status is not None:
        statement = statement.where(Expense.status == status)
    if duplicate_status is not None:
        statement = statement.where(Expense.duplicate_status == duplicate_status)
    return int(db.scalar(statement) or 0)


def server_settings_snapshot(db: Session) -> dict[str, int | bool | str]:
    settings = get_settings()
    return {
        "max_upload_size_mb": settings.max_upload_size_mb,
        "generate_thumbnail": settings.generate_thumbnail,
        "delete_image_after_confirm": settings.delete_image_after_confirm,
        "delete_image_after_days": settings.delete_image_after_days,
        "ocr_provider": settings.ocr_provider,
        "pending_count": _count_expenses(db, status="pending"),
        "confirmed_count": _count_expenses(db, status="confirmed"),
        "rejected_count": _count_expenses(db, status="rejected"),
        "suspected_duplicate_count": _count_expenses(db, duplicate_status="suspected"),
        "upload_storage_bytes": _upload_storage_bytes(),
    }
