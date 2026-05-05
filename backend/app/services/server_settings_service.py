from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, get_settings
from app.models import Expense
from app.services.time_service import to_iso


def _upload_storage_bytes(db: Session, tenant_id: str) -> int:
    settings = get_settings()
    total = 0
    paths = db.scalars(
        select(Expense.image_path)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.image_path.is_not(None))
    )
    for relative_path in paths:
        if not relative_path:
            continue
        candidate = (BACKEND_ROOT / relative_path).resolve()
        try:
            candidate.relative_to(settings.upload_dir)
        except ValueError:
            continue
        if candidate.is_file():
            total += candidate.stat().st_size
    return total


def _count_expenses(db: Session, *, tenant_id: str, status: str | None = None, duplicate_status: str | None = None) -> int:
    statement = select(func.count()).select_from(Expense).where(Expense.tenant_id == tenant_id)
    if status is not None:
        statement = statement.where(Expense.status == status)
    if duplicate_status is not None:
        statement = statement.where(Expense.duplicate_status == duplicate_status)
    return int(db.scalar(statement) or 0)


def server_settings_snapshot(db: Session, tenant_id: str, tenant_name: str) -> dict[str, int | bool | str | float | None]:
    settings = get_settings()
    latest_upload_at = db.scalar(select(func.max(Expense.created_at)).where(Expense.tenant_id == tenant_id))
    return {
        "tenant_name": tenant_name,
        "max_upload_size_mb": settings.max_upload_size_mb,
        "generate_thumbnail": settings.generate_thumbnail,
        "delete_image_after_confirm": settings.delete_image_after_confirm,
        "delete_image_after_days": settings.delete_image_after_days,
        "ocr_provider": settings.ocr_provider,
        "ocr_auto_run": settings.ocr_auto_run,
        "ocr_fallback_provider": settings.ocr_fallback_provider,
        "ocr_min_confidence": settings.ocr_min_confidence,
        "pending_count": _count_expenses(db, tenant_id=tenant_id, status="pending"),
        "confirmed_count": _count_expenses(db, tenant_id=tenant_id, status="confirmed"),
        "rejected_count": _count_expenses(db, tenant_id=tenant_id, status="rejected"),
        "suspected_duplicate_count": _count_expenses(db, tenant_id=tenant_id, duplicate_status="suspected"),
        "upload_storage_bytes": _upload_storage_bytes(db, tenant_id),
        "latest_upload_at": to_iso(latest_upload_at),
    }
