"""Account-scoped UI preferences (theme, etc.).

Route handlers must not call DB directly — see ENGINEERING_RULES §1
"routes 不写业务、不拼复杂 SQL". All preference read/write goes through here.

Owner Console is intentionally NOT a participant: single-device loopback role.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.system import UserUiPreference
from app.schemas import UserUiPreferencesResponse, UserUiPreferencesUpdateRequest

__all__ = [
    "VALID_THEMES",
    "get_ui_preferences",
    "upsert_ui_preferences",
]

VALID_THEMES = frozenset({"paper", "mono", "midnight"})


def _parse(pref: UserUiPreference | None) -> dict:
    if pref is None or not pref.preferences:
        return {}
    try:
        data = json.loads(pref.preferences)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _to_response(pref: UserUiPreference | None) -> UserUiPreferencesResponse:
    data = _parse(pref)
    theme = data.get("theme")
    return UserUiPreferencesResponse(
        theme=theme if theme in VALID_THEMES else None,
        updated_at=pref.updated_at if pref else None,
    )


def _load(db: Session, *, account_id: str) -> UserUiPreference | None:
    return (
        db.query(UserUiPreference)
        .filter(UserUiPreference.account_id == account_id)
        .first()
    )


def get_ui_preferences(db: Session, *, account_id: str) -> UserUiPreferencesResponse:
    return _to_response(_load(db, account_id=account_id))


def upsert_ui_preferences(
    db: Session,
    *,
    account_id: str,
    account_name: str,
    payload: UserUiPreferencesUpdateRequest,
) -> UserUiPreferencesResponse:
    pref = _load(db, account_id=account_id)
    current = _parse(pref)
    # Invalid theme values are silently dropped, not rejected, to keep the endpoint forgiving
    # for clients that may roll new theme keys (V0.11+) before the server understands them.
    if payload.theme is not None and payload.theme in VALID_THEMES:
        current["theme"] = payload.theme
    encoded = json.dumps(current, ensure_ascii=False)
    if pref is None:
        pref = UserUiPreference(
            account_id=account_id,
            account_name=account_name,
            preferences=encoded,
        )
        db.add(pref)
    else:
        pref.account_name = account_name
        pref.preferences = encoded
    db.commit()
    db.refresh(pref)
    return _to_response(pref)
