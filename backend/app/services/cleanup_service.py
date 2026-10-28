from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import (
    CategoryPreference,
    CategoryRule,
    DebtBillCapture,
    Expense,
    MerchantAlias,
    MerchantCatalog,
    Tag,
    TagMutationUndoGroup,
    TagMutationUndoItem,
)
from app.services import permission_service
from app.services.admin_scope_service import lock_and_resolve_mutation_ledger_ids
from app.services.attachment_cleanup_service import execute_attachment_cleanup
from app.services.currency_binding_service import (
    authorize_currency_metadata_write,
)
from app.services.orphan_upload_service import OrphanCleanupResult, run_orphan_cleanup
from app.services.soft_delete_policy import recycle_bin_retention_days
from app.services.time_service import now_utc
from app.tenants import AuthContext


@dataclass(frozen=True)
class CleanupResult:
    enabled: bool
    delete_after_days: int
    scanned: int
    deleted_images: int
    deleted_thumbnails: int


def cleanup_after_confirm(db: Session, expense: Expense | DebtBillCapture) -> bool:
    """Own GC commits after the caller has committed this confirmed Expense.

    The return value reports cleanup metadata change; callers must not add a
    second cleanup commit or refresh after this owner's completed transactions.
    """
    settings = get_settings()
    if not settings.delete_image_after_confirm:
        return False
    return execute_attachment_cleanup(db, expense, reason="after_confirm", settings_provider=get_settings).changed


def _authorize_cleanup(db: Session, tenant_id: str, auth: AuthContext | None) -> None:
    # None is reserved for trusted internal maintenance. Network callers keep
    # their credential through every commit, including the pre-unlink check.
    if auth is None:
        return
    permission_service.require_admin_maintenance(auth)
    ledger_ids = lock_and_resolve_mutation_ledger_ids(
        db, auth=auth, actor_account_id=auth.account_id, requested_ledger_ids={tenant_id},
    )
    if ledger_ids is None or tenant_id not in ledger_ids:
        raise AppError("permission_denied", status_code=403)


def _cleanup_retained_images(
    db: Session, tenant_id: str, *, status: str, auth: AuthContext | None,
) -> CleanupResult:
    _authorize_cleanup(db, tenant_id, auth)
    settings = get_settings()
    days = settings.delete_image_after_days if status == "confirmed" else settings.delete_rejected_after_days
    original_time = Expense.confirmed_at if status == "confirmed" else Expense.rejected_at
    cutoff = now_utc() - timedelta(days=days)
    expenses = list(db.scalars(select(Expense).where(
        Expense.tenant_id == tenant_id,
        or_(Expense.attachment_cleanup_request.is_not(None),
            and_(days > 0, Expense.status == status,
                 func.greatest(original_time, Expense.image_replenished_at) <= cutoff)),
    )))
    source_time = DebtBillCapture.confirmed_at if status == "confirmed" else DebtBillCapture.rejected_at
    sources = list(db.scalars(select(DebtBillCapture).where(
        DebtBillCapture.tenant_id == tenant_id,
        or_(DebtBillCapture.attachment_cleanup_request.is_not(None),
            and_(days > 0, DebtBillCapture.status == status, source_time <= cutoff)),
    )))
    deleted_images = deleted_thumbnails = 0
    for expense in [*expenses, *sources]:
        result = execute_attachment_cleanup(
            db, expense, reason=f"{status}_retention", settings_provider=get_settings,
            actor_account_id=auth.account_id if auth else None,
            authorize=lambda: _authorize_cleanup(db, tenant_id, auth),
        )
        deleted_images += result.deleted_images
        deleted_thumbnails += result.deleted_thumbnails
    return CleanupResult(days > 0, days, len(expenses) + len(sources), deleted_images, deleted_thumbnails)


def cleanup_confirmed_images(db: Session, tenant_id: str, *, auth: AuthContext | None = None) -> CleanupResult:
    return _cleanup_retained_images(db, tenant_id, status="confirmed", auth=auth)


def cleanup_rejected_images(db: Session, tenant_id: str, *, auth: AuthContext | None = None) -> CleanupResult:
    return _cleanup_retained_images(db, tenant_id, status="rejected", auth=auth)


def cleanup_orphan_uploads(
    db: Session, tenant_id: str, *, dry_run: bool = True, auth: AuthContext | None = None,
) -> OrphanCleanupResult:
    return run_orphan_cleanup(db, tenant_id, settings=get_settings(), dry_run=dry_run,
                              authorize=lambda: _authorize_cleanup(db, tenant_id, auth))


def purge_expired_soft_deletes(
    db: Session,
    *,
    retention_days: int | None = None,
    retention_minutes: int | None = None,
    now: datetime | None = None,
) -> int:
    """Global (all-tenant) purge of soft-deleted rows past recycle retention.

    Covers every resource that participates in soft-delete undo:
    ``merchant_aliases``, ``merchant_catalog``, ``category_rules``, and the ADR-0043 tag-mutation undo
    snapshots (``tag_mutation_undo_groups`` + ``_items``), the soft-deleted
    ``tags`` they anchor, and ADR-0052 custom category preferences. Rows are hidden
    from every read the moment they are
    soft-deleted, so the sweep cadence only bounds storage lag, never read
    correctness or the short undo window.
    """
    authorize_currency_metadata_write(db, allow_empty_category_rule=True)
    cutoff = _soft_delete_purge_cutoff(
        now=now,
        retention_days=retention_days,
        retention_minutes=retention_minutes,
    )
    alias_result = db.execute(
        delete(MerchantAlias).where(MerchantAlias.deleted_at.is_not(None)).where(MerchantAlias.deleted_at < cutoff)
    )
    rule_result = db.execute(
        delete(CategoryRule).where(CategoryRule.deleted_at.is_not(None)).where(CategoryRule.deleted_at < cutoff)
    )
    category_result = db.execute(
        delete(CategoryPreference)
        .where(CategoryPreference.deleted_at.is_not(None))
        .where(CategoryPreference.deleted_at < cutoff)
    )
    merchant_catalog_result = db.execute(
        delete(MerchantCatalog)
        .where(MerchantCatalog.deleted_at.is_not(None))
        .where(MerchantCatalog.deleted_at < cutoff)
    )
    # ADR-0043 契约 6: snapshot retention anchors on the GROUP's own created_at.
    # Items first (composite FK → groups), then groups, then the still-soft-
    # deleted tags whose own deleted_at is past the window. The snapshot tables
    # have no FK to ``tags`` (source/target stored as public_id), so group/tag
    # purges are independent — a revived tag (live) is left alone, a tag still
    # soft-deleted past window is freed (releasing its reserved unique key).
    expired_group_ids = select(TagMutationUndoGroup.id).where(TagMutationUndoGroup.created_at < cutoff)
    db.execute(delete(TagMutationUndoItem).where(TagMutationUndoItem.group_id.in_(expired_group_ids)))
    group_result = db.execute(delete(TagMutationUndoGroup).where(TagMutationUndoGroup.created_at < cutoff))
    tag_result = db.execute(delete(Tag).where(Tag.deleted_at.is_not(None)).where(Tag.deleted_at < cutoff))
    db.commit()
    return (
        int(alias_result.rowcount or 0)
        + int(rule_result.rowcount or 0)
        + int(category_result.rowcount or 0)
        + int(merchant_catalog_result.rowcount or 0)
        + int(group_result.rowcount or 0)
        + int(tag_result.rowcount or 0)
    )


def _soft_delete_purge_cutoff(
    *,
    now: datetime | None,
    retention_days: int | None,
    retention_minutes: int | None,
) -> datetime:
    base = now or now_utc()
    if retention_minutes is not None:
        return base - timedelta(minutes=max(0, int(retention_minutes)))
    keep_days = recycle_bin_retention_days() if retention_days is None else max(0, int(retention_days))
    return base - timedelta(days=keep_days)
