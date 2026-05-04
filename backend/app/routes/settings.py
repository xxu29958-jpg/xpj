from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import verify_app_token
from app.database import get_db
from app.schemas import ServerSettingsResponse
from app.services.server_settings_service import server_settings_snapshot


router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(verify_app_token)],
)


@router.get("/server", response_model=ServerSettingsResponse)
def get_server_settings(db: Session = Depends(get_db)) -> ServerSettingsResponse:
    return ServerSettingsResponse(**server_settings_snapshot(db))
