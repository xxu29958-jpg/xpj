from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import verify_admin_token
from app.database import get_db
from app.schemas import MaintenanceCleanupResponse
from app.services.cleanup_service import cleanup_confirmed_images


router = APIRouter(
    prefix="/api/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(verify_admin_token)],
)


@router.post("/cleanup-images", response_model=MaintenanceCleanupResponse)
def post_cleanup_images(db: Session = Depends(get_db)) -> MaintenanceCleanupResponse:
    result = cleanup_confirmed_images(db)
    return MaintenanceCleanupResponse(
        enabled=result.enabled,
        delete_after_days=result.delete_after_days,
        scanned=result.scanned,
        deleted_images=result.deleted_images,
        deleted_thumbnails=result.deleted_thumbnails,
    )
