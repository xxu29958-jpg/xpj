from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, get_settings
from app.models import Expense
from app.services.file_service import ALLOWED_EXTENSIONS
from app.services.time_service import now_utc


@dataclass(frozen=True)
class CleanupResult:
    enabled: bool
    delete_after_days: int
    scanned: int
    deleted_images: int
    deleted_thumbnails: int


@dataclass(frozen=True)
class OrphanCleanupResult:
    dry_run: bool
    grace_hours: int
    scanned_files: int
    orphan_files: int
    deleted_files: int
    orphan_bytes: int
    deleted_bytes: int


def _delete_relative_file(relative_path: str | None, tenant_id: str) -> bool:
    if not relative_path:
        return False
    settings = get_settings()
    tenant_upload_dir = (settings.upload_dir / tenant_id).resolve()
    candidate = (BACKEND_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(settings.upload_dir)
        candidate.relative_to(tenant_upload_dir)
    except ValueError:
        return False
    if candidate.is_file():
        candidate.unlink()
        return True
    return False


def _relative_upload_path(path: Path) -> str | None:
    settings = get_settings()
    candidate = path.resolve()
    try:
        candidate.relative_to(settings.upload_dir)
    except ValueError:
        return None
    try:
        return candidate.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return None


def _referenced_upload_paths(db: Session, tenant_id: str) -> set[str]:
    rows = db.execute(
        select(Expense.image_path, Expense.thumbnail_path)
        .where(Expense.tenant_id == tenant_id)
        .where(
            or_(
                Expense.image_path.is_not(None),
                Expense.thumbnail_path.is_not(None),
            )
        )
    )
    referenced: set[str] = set()
    for image_path, thumbnail_path in rows:
        if image_path:
            referenced.add(image_path)
        if thumbnail_path:
            referenced.add(thumbnail_path)
    return referenced


def _is_supported_upload_file(path: Path) -> bool:
    suffix = path.suffix.lower().removeprefix(".")
    return suffix in ALLOWED_EXTENSIONS or suffix == "jpg"


def cleanup_after_confirm(expense: Expense) -> Expense:
    settings = get_settings()
    if not settings.delete_image_after_confirm:
        return expense

    now = now_utc()
    if _delete_relative_file(expense.image_path, expense.tenant_id):
        expense.image_deleted_at = now
    return expense


def cleanup_confirmed_images(db: Session, tenant_id: str) -> CleanupResult:
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
                Expense.tenant_id == tenant_id,
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
        if expense.image_deleted_at is None and _delete_relative_file(expense.image_path, expense.tenant_id):
            expense.image_deleted_at = now
            deleted_images += 1
            changed = True
        if expense.thumbnail_deleted_at is None and _delete_relative_file(expense.thumbnail_path, expense.tenant_id):
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


def cleanup_rejected_images(db: Session, tenant_id: str) -> CleanupResult:
    settings = get_settings()
    if settings.delete_rejected_after_days <= 0:
        return CleanupResult(
            enabled=False,
            delete_after_days=settings.delete_rejected_after_days,
            scanned=0,
            deleted_images=0,
            deleted_thumbnails=0,
        )

    cutoff = now_utc() - timedelta(days=settings.delete_rejected_after_days)
    expenses = list(
        db.scalars(
            select(Expense).where(
                Expense.tenant_id == tenant_id,
                Expense.status == "rejected",
                Expense.rejected_at.is_not(None),
                Expense.rejected_at <= cutoff,
            ),
        ),
    )

    now = now_utc()
    deleted_images = 0
    deleted_thumbnails = 0
    for expense in expenses:
        changed = False
        if expense.image_deleted_at is None and _delete_relative_file(expense.image_path, expense.tenant_id):
            expense.image_deleted_at = now
            deleted_images += 1
            changed = True
        if expense.thumbnail_deleted_at is None and _delete_relative_file(expense.thumbnail_path, expense.tenant_id):
            expense.thumbnail_deleted_at = now
            deleted_thumbnails += 1
            changed = True
        if changed:
            expense.updated_at = now

    if deleted_images or deleted_thumbnails:
        db.commit()

    return CleanupResult(
        enabled=True,
        delete_after_days=settings.delete_rejected_after_days,
        scanned=len(expenses),
        deleted_images=deleted_images,
        deleted_thumbnails=deleted_thumbnails,
    )


def cleanup_orphan_uploads(db: Session, tenant_id: str, *, dry_run: bool = True) -> OrphanCleanupResult:
    settings = get_settings()
    tenant_upload_dir = (settings.upload_dir / tenant_id).resolve()
    referenced = _referenced_upload_paths(db, tenant_id)
    cutoff = now_utc() - timedelta(hours=max(settings.orphan_upload_grace_hours, 0))

    scanned_files = 0
    orphan_files = 0
    deleted_files = 0
    orphan_bytes = 0
    deleted_bytes = 0

    if not tenant_upload_dir.exists():
        return OrphanCleanupResult(
            dry_run=dry_run,
            grace_hours=settings.orphan_upload_grace_hours,
            scanned_files=0,
            orphan_files=0,
            deleted_files=0,
            orphan_bytes=0,
            deleted_bytes=0,
        )

    for path in tenant_upload_dir.rglob("*"):
        if not path.is_file() or not _is_supported_upload_file(path):
            continue
        relative_path = _relative_upload_path(path)
        if relative_path is None:
            continue
        scanned_files += 1
        if relative_path in referenced:
            continue

        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if modified_at > cutoff:
            continue

        size = path.stat().st_size
        orphan_files += 1
        orphan_bytes += size
        if not dry_run:
            path.unlink(missing_ok=True)
            deleted_files += 1
            deleted_bytes += size

    return OrphanCleanupResult(
        dry_run=dry_run,
        grace_hours=settings.orphan_upload_grace_hours,
        scanned_files=scanned_files,
        orphan_files=orphan_files,
        deleted_files=deleted_files,
        orphan_bytes=orphan_bytes,
        deleted_bytes=deleted_bytes,
    )
