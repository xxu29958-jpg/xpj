from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import ServerSettingsResponse
from app.services.server_settings_service import server_settings_snapshot
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
)


@router.get("/server", response_model=ServerSettingsResponse)
def get_server_settings(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ServerSettingsResponse:
    return ServerSettingsResponse(
        **server_settings_snapshot(
            db,
            ledger_id=auth.ledger_id,
            account_name=auth.account_name,
            ledger_name=auth.ledger_name,
            device_name=auth.device_name,
            role=auth.role,
        )
    )
