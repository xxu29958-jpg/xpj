from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CategoryRule, Expense, MerchantAlias
from app.services.file_service import (
    ALLOWED_EXTENSIONS,
    resolve_upload_path_for_tenant,
    upload_reference_for_path,
)
from app.services.soft_delete_policy import SOFT_DELETE_RETENTION_MINUTES
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


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
    candidate = _resolve_relative_file(relative_path, tenant_id)
    if candidate is None:
        return False
    if candidate.is_file():
        try:
            candidate.unlink()
            return True
        except OSError:
            return False
    return False


def _delete_relative_file_for_db_mark(relative_path: str | None, tenant_id: str) -> tuple[bool, bool]:
    """Return ``(can_mark_deleted, physical_file_deleted)`` for a DB file reference."""

    candidate = _resolve_relative_file(relative_path, tenant_id)
    if candidate is None:
        return False, False
    if not candidate.exists():
        return True, False
    if not candidate.is_file():
        return False, False
    try:
        candidate.unlink()
    except OSError:
        return False, False
    return True, True


def _resolve_relative_file(relative_path: str | None, tenant_id: str) -> Path | None:
    return resolve_upload_path_for_tenant(relative_path, tenant_id)


def _relative_file_exists(relative_path: str | None, tenant_id: str) -> bool:
    candidate = _resolve_relative_file(relative_path, tenant_id)
    return candidate is not None and candidate.is_file()


def _relative_upload_path(path: Path) -> str | None:
    try:
        return upload_reference_for_path(path)
    except RuntimeError:
        return None


def _normalize_upload_reference(relative_path: str | None, tenant_id: str) -> str | None:
    if not relative_path:
        return None
    candidate = resolve_upload_path_for_tenant(relative_path, tenant_id)
    if candidate is None:
        return None
    return _relative_upload_path(candidate)


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
        normalized_image = _normalize_upload_reference(image_path, tenant_id)
        if normalized_image:
            referenced.add(normalized_image)
        normalized_thumbnail = _normalize_upload_reference(thumbnail_path, tenant_id)
        if normalized_thumbnail:
            referenced.add(normalized_thumbnail)
    return referenced


def _is_supported_upload_file(path: Path) -> bool:
    suffix = path.suffix.lower().removeprefix(".")
    return suffix in ALLOWED_EXTENSIONS or suffix == "jpg"


def cleanup_after_confirm(expense: Expense) -> bool:
    settings = get_settings()
    if not settings.delete_image_after_confirm:
        return False

    now = now_utc()
    changed = False
    if expense.image_deleted_at is None:
        can_mark_image, _deleted_image = _delete_relative_file_for_db_mark(
            expense.image_path, expense.tenant_id
        )
        if can_mark_image:
            expense.image_deleted_at = now
            changed = True
    if expense.thumbnail_deleted_at is None:
        can_mark_thumbnail, _deleted_thumbnail = _delete_relative_file_for_db_mark(
            expense.thumbnail_path, expense.tenant_id
        )
        if can_mark_thumbnail:
            expense.thumbnail_deleted_at = now
            changed = True
    if changed:
        expense.updated_at = now
    return changed


def delete_after_confirm_files(expense: Expense) -> None:
    cleanup_after_confirm(expense)


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
    changed = False
    deleted_images = 0
    deleted_thumbnails = 0
    for expense in expenses:
        expense_changed = False
        if expense.image_deleted_at is None:
            can_mark_image, deleted_image = _delete_relative_file_for_db_mark(
                expense.image_path, expense.tenant_id
            )
            if can_mark_image:
                expense.image_deleted_at = now
                deleted_images += int(deleted_image)
                expense_changed = True
        if expense.thumbnail_deleted_at is None:
            can_mark_thumbnail, deleted_thumbnail = _delete_relative_file_for_db_mark(
                expense.thumbnail_path, expense.tenant_id
            )
            if can_mark_thumbnail:
                expense.thumbnail_deleted_at = now
                deleted_thumbnails += int(deleted_thumbnail)
                expense_changed = True
        if expense_changed:
            expense.updated_at = now
            changed = True

    if changed:
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
    changed = False
    deleted_images = 0
    deleted_thumbnails = 0
    for expense in expenses:
        expense_changed = False
        if expense.image_deleted_at is None:
            can_mark_image, deleted_image = _delete_relative_file_for_db_mark(
                expense.image_path, expense.tenant_id
            )
            if can_mark_image:
                expense.image_deleted_at = now
                deleted_images += int(deleted_image)
                expense_changed = True
        if expense.thumbnail_deleted_at is None:
            can_mark_thumbnail, deleted_thumbnail = _delete_relative_file_for_db_mark(
                expense.thumbnail_path, expense.tenant_id
            )
            if can_mark_thumbnail:
                expense.thumbnail_deleted_at = now
                deleted_thumbnails += int(deleted_thumbnail)
                expense_changed = True
        if expense_changed:
            expense.updated_at = now
            changed = True

    if changed:
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

    scan_roots = [tenant_upload_dir] if tenant_upload_dir.exists() else []
    if tenant_id == DEFAULT_TENANT_ID and settings.upload_dir.exists():
        scan_roots.append(settings.upload_dir.resolve())

    if not scan_roots:
        return OrphanCleanupResult(
            dry_run=dry_run,
            grace_hours=settings.orphan_upload_grace_hours,
            scanned_files=0,
            orphan_files=0,
            deleted_files=0,
            orphan_bytes=0,
            deleted_bytes=0,
        )

    seen: set[str] = set()
    for root in scan_roots:
        for path in root.rglob("*"):
            try:
                if not path.is_file() or not _is_supported_upload_file(path):
                    continue
                relative_path = _relative_upload_path(path)
                if relative_path is None or relative_path in seen:
                    continue
                if _resolve_relative_file(relative_path, tenant_id) is None:
                    continue
                stat = path.stat()
            except OSError:
                continue

            seen.add(relative_path)
            scanned_files += 1
            if relative_path in referenced:
                continue

            modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
            if modified_at > cutoff:
                continue

            size = stat.st_size
            orphan_files += 1
            orphan_bytes += size
            if not dry_run:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
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


def purge_expired_soft_deleted_merchant_aliases(
    db: Session,
    tenant_id: str,
    *,
    retention_minutes: int = SOFT_DELETE_RETENTION_MINUTES,
    now: datetime | None = None,
) -> int:
    """ADR-0038 undo: permanently delete merchant_aliases soft-deleted past the
    retention window. Returns the number of rows purged.

    Tenant-scoped so an admin/maintenance call cannot purge other ledgers.
    Rows still inside the window stay recoverable via the undo endpoint.
    """
    cutoff = (now or now_utc()) - timedelta(minutes=retention_minutes)
    result = db.execute(
        delete(MerchantAlias)
        .where(MerchantAlias.tenant_id == tenant_id)
        .where(MerchantAlias.deleted_at.is_not(None))
        .where(MerchantAlias.deleted_at < cutoff)
    )
    db.commit()
    return int(result.rowcount or 0)


def purge_expired_soft_deletes(
    db: Session,
    *,
    retention_minutes: int = SOFT_DELETE_RETENTION_MINUTES,
    now: datetime | None = None,
) -> int:
    """ADR-0038 undo: global (all-tenant) purge of soft-deleted rows past the
    retention window, for the periodic purge scheduler. Returns rows purged.

    Covers every resource that participates in soft-delete undo. Today that is
    ``merchant_aliases`` and ``category_rules``; extend this as the undo pattern
    reaches more tables. Rows are hidden from every read the moment they are
    soft-deleted, so the sweep cadence only bounds storage lag, never
    correctness or the undo window.
    """
    cutoff = (now or now_utc()) - timedelta(minutes=retention_minutes)
    alias_result = db.execute(
        delete(MerchantAlias)
        .where(MerchantAlias.deleted_at.is_not(None))
        .where(MerchantAlias.deleted_at < cutoff)
    )
    rule_result = db.execute(
        delete(CategoryRule)
        .where(CategoryRule.deleted_at.is_not(None))
        .where(CategoryRule.deleted_at < cutoff)
    )
    db.commit()
    return int(alias_result.rowcount or 0) + int(rule_result.rowcount or 0)
