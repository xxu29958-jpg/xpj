"""v0.10: cross-surface UI preferences (theme, etc.) per account.

GET /api/me/ui-preferences   - read current preferences (defaults if missing)
PUT /api/me/ui-preferences   - upsert; ignored if invalid

Owner Console does NOT participate (single-device loopback role). Web + Android share.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import UserUiPreferencesResponse, UserUiPreferencesUpdateRequest
from app.services.user_preferences_service import (
    get_ui_preferences,
    upsert_ui_preferences,
)
from app.tenants import AuthContext

router = APIRouter(prefix="/api/me", tags=["user-preferences"])


@router.get("/ui-preferences", response_model=UserUiPreferencesResponse)
def get_preferences(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> UserUiPreferencesResponse:
    return get_ui_preferences(db, account_id=auth.account_id)


@router.put("/ui-preferences", response_model=UserUiPreferencesResponse)
def put_preferences(
    payload: UserUiPreferencesUpdateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> UserUiPreferencesResponse:
    return upsert_ui_preferences(
        db,
        account_id=auth.account_id,
        account_name=auth.account_name,
        payload=payload,
    )
