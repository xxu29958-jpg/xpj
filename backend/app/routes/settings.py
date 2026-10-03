from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_app_principal
from app.database import get_db
from app.schemas import ServerSettingsResponse
from app.schemas._account_profile import AccountProfileRenameRequest, AccountProfileResponse
from app.services import account_profile_service
from app.services.server_settings_service import server_settings_snapshot
from app.tenants import AuthContext, SessionPrincipal

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
)


@router.get("/account", response_model=AccountProfileResponse)
def get_account_profile(response: Response, principal: SessionPrincipal = Depends(get_current_app_principal),
                        db: Session = Depends(get_db)) -> AccountProfileResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return AccountProfileResponse(**asdict(account_profile_service.read_profile(db, principal)))


@router.post("/account", response_model=AccountProfileResponse)
def rename_account_profile(payload: AccountProfileRenameRequest, response: Response,
                           principal: SessionPrincipal = Depends(get_current_app_principal),
                           db: Session = Depends(get_db)) -> AccountProfileResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return AccountProfileResponse(**asdict(account_profile_service.rename_profile(
        db, principal, display_name=payload.display_name, expected_name=payload.expected_name)))


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
