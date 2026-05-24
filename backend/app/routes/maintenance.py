from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import verify_admin_token
from app.database import get_db
from app.network_boundary import require_admin_network_boundary
from app.schemas import (
    MaintenanceAuditCleanupResponse,
    MaintenanceCleanupResponse,
    MaintenanceOrphanCleanupResponse,
)
from app.services.budget_advisor_service import cleanup_expired_audit_logs
from app.services.cleanup_service import cleanup_confirmed_images, cleanup_orphan_uploads, cleanup_rejected_images
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_admin_network_boundary)],
)


@router.post("/cleanup-images", response_model=MaintenanceCleanupResponse)
def post_cleanup_images(
    auth: AuthContext = Depends(verify_admin_token),
    db: Session = Depends(get_db),
) -> MaintenanceCleanupResponse:
    result = cleanup_confirmed_images(db, auth.tenant_id)
    return MaintenanceCleanupResponse(
        enabled=result.enabled,
        delete_after_days=result.delete_after_days,
        scanned=result.scanned,
        deleted_images=result.deleted_images,
        deleted_thumbnails=result.deleted_thumbnails,
    )


@router.post("/cleanup-rejected", response_model=MaintenanceCleanupResponse)
def post_cleanup_rejected(
    auth: AuthContext = Depends(verify_admin_token),
    db: Session = Depends(get_db),
) -> MaintenanceCleanupResponse:
    result = cleanup_rejected_images(db, auth.tenant_id)
    return MaintenanceCleanupResponse(
        enabled=result.enabled,
        delete_after_days=result.delete_after_days,
        scanned=result.scanned,
        deleted_images=result.deleted_images,
        deleted_thumbnails=result.deleted_thumbnails,
    )


@router.post("/cleanup-orphans", response_model=MaintenanceOrphanCleanupResponse)
def post_cleanup_orphans(
    auth: AuthContext = Depends(verify_admin_token),
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> MaintenanceOrphanCleanupResponse:
    result = cleanup_orphan_uploads(db, auth.tenant_id, dry_run=dry_run)
    return MaintenanceOrphanCleanupResponse(
        dry_run=result.dry_run,
        grace_hours=result.grace_hours,
        scanned_files=result.scanned_files,
        orphan_files=result.orphan_files,
        deleted_files=result.deleted_files,
        orphan_bytes=result.orphan_bytes,
        deleted_bytes=result.deleted_bytes,
    )


@router.post(
    "/cleanup-ai-advisor-audit",
    response_model=MaintenanceAuditCleanupResponse,
)
def post_cleanup_ai_advisor_audit(
    auth: AuthContext = Depends(verify_admin_token),
    batch_size: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> MaintenanceAuditCleanupResponse:
    _ = auth
    deleted = cleanup_expired_audit_logs(db, batch_size=batch_size)
    return MaintenanceAuditCleanupResponse(
        deleted_rows=deleted,
        batch_size=batch_size,
    )
