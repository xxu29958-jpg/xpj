"""v0.10: cross-surface UI preferences (theme, etc.) per account_name.

GET /api/me/ui-preferences   - read current preferences (defaults if missing)
PUT /api/me/ui-preferences   - upsert; ignored if invalid

Owner Console does NOT participate (single-device loopback role). Web + Android share.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.models.system import UserUiPreference
from app.schemas import UserUiPreferencesResponse, UserUiPreferencesUpdateRequest
from app.tenants import AuthContext

router = APIRouter(prefix="/api/me", tags=["user-preferences"])

_VALID_THEMES = {"paper", "mono", "midnight"}


def _parse(pref: UserUiPreference | None) -> dict:
    if pref is None or not pref.preferences:
        return {}
    try:
        data = json.loads(pref.preferences)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _to_response(pref: UserUiPreference | None) -> UserUiPreferencesResponse:
    data = _parse(pref)
    theme = data.get("theme")
    return UserUiPreferencesResponse(
        theme=theme if theme in _VALID_THEMES else None,
        updated_at=pref.updated_at if pref else None,
    )


@router.get("/ui-preferences", response_model=UserUiPreferencesResponse)
def get_preferences(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> UserUiPreferencesResponse:
    pref = (
        db.query(UserUiPreference)
        .filter(UserUiPreference.account_name == auth.account_name)
        .first()
    )
    return _to_response(pref)


@router.put("/ui-preferences", response_model=UserUiPreferencesResponse)
def put_preferences(
    payload: UserUiPreferencesUpdateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> UserUiPreferencesResponse:
    pref = (
        db.query(UserUiPreference)
        .filter(UserUiPreference.account_name == auth.account_name)
        .first()
    )
    current = _parse(pref)
    # Invalid theme values are silently dropped, not rejected, to keep the endpoint forgiving
    # for clients that may roll new theme keys (V0.11+) before the server understands them.
    if payload.theme is not None and payload.theme in _VALID_THEMES:
        current["theme"] = payload.theme
    encoded = json.dumps(current, ensure_ascii=False)
    if pref is None:
        pref = UserUiPreference(account_name=auth.account_name, preferences=encoded)
        db.add(pref)
    else:
        pref.preferences = encoded
    db.commit()
    db.refresh(pref)
    return _to_response(pref)
