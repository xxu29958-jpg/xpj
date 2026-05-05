from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_tenant
from app.database import get_db
from app.schemas import ServerSettingsResponse
from app.services.server_settings_service import server_settings_snapshot
from app.tenants import Tenant


router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
)


@router.get("/server", response_model=ServerSettingsResponse)
def get_server_settings(
    tenant: Tenant = Depends(get_current_app_tenant),
    db: Session = Depends(get_db),
) -> ServerSettingsResponse:
    return ServerSettingsResponse(**server_settings_snapshot(db, tenant.id, tenant.name))
