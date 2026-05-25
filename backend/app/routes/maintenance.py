from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import verify_admin_token
from app.database import get_db
from app.network_boundary import require_admin_network_boundary
from app.schemas import (
    LearningCleanupReportResponse,
    LearningMaintenanceRunResponse,
    LearningStatusOverviewResponse,
    LearningTableSnapshotResponse,
    MaintenanceAuditCleanupResponse,
    MaintenanceCleanupResponse,
    MaintenanceOrphanCleanupResponse,
)
from app.services.budget_advisor_service import cleanup_expired_audit_logs
from app.services.cleanup_service import cleanup_confirmed_images, cleanup_orphan_uploads, cleanup_rejected_images
from app.services.learning_service import (
    get_status_overview,
    run_full_maintenance,
)
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


@router.get(
    "/learning-status",
    response_model=LearningStatusOverviewResponse,
)
def get_learning_status(
    auth: AuthContext = Depends(verify_admin_token),
    db: Session = Depends(get_db),
) -> LearningStatusOverviewResponse:
    """v1.2 ops: per-table snapshot for the Owner Console panel."""

    _ = auth
    overview = get_status_overview(db)
    return LearningStatusOverviewResponse(
        algorithm_decisions=LearningTableSnapshotResponse(
            total_rows=overview.algorithm_decisions.total_rows,
            expired_candidate_rows=overview.algorithm_decisions.expired_candidate_rows,
        ),
        ledger_learning_events=LearningTableSnapshotResponse(
            total_rows=overview.ledger_learning_events.total_rows,
            expired_candidate_rows=overview.ledger_learning_events.expired_candidate_rows,
        ),
        ocr_facts=LearningTableSnapshotResponse(
            total_rows=overview.ocr_facts.total_rows,
            expired_candidate_rows=overview.ocr_facts.expired_candidate_rows,
        ),
        active_decisions=overview.active_decisions,
        stale_active_candidates=overview.stale_active_candidates,
        last_cleanup_at=overview.last_cleanup_at,
        last_cleanup_summary=overview.last_cleanup_summary,
    )


@router.post(
    "/cleanup-learning",
    response_model=LearningMaintenanceRunResponse,
)
def post_cleanup_learning(
    auth: AuthContext = Depends(verify_admin_token),
    batch_size: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> LearningMaintenanceRunResponse:
    """v1.2 ops: sweep stale active decisions, prune expired rows,
    stamp ``app_meta.learning_cleanup_last_run_at``."""

    _ = auth
    result = run_full_maintenance(db, batch_size=batch_size)
    return LearningMaintenanceRunResponse(
        swept_stale_active=result.swept_stale_active,
        cleanup=LearningCleanupReportResponse(
            algorithm_decisions=result.cleanup.algorithm_decisions,
            ledger_learning_events=result.cleanup.ledger_learning_events,
            ocr_facts=result.cleanup.ocr_facts,
            total=result.cleanup.total,
        ),
        finished_at=result.finished_at,
        elapsed_ms=result.elapsed_ms,
    )
