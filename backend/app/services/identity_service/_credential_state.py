"""Closed lifecycle projection for an authenticated session credential."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuthToken
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext

SessionCredentialState = Literal["current", "grace"]


def _session_credential_state(
    token: AuthToken,
    *,
    now: datetime,
) -> SessionCredentialState | None:
    if token.revoked_at is None:
        return "current"
    if token.scope != "app":
        return None
    grace_until = ensure_utc(token.grace_until)
    if grace_until is not None and grace_until > now:
        return "grace"
    return None


def authenticated_session_credential_state(
    db: Session,
    auth: AuthContext,
) -> SessionCredentialState:
    """Project the lifecycle state of the credential that produced ``auth``.

    The durable owner remains ``AuthToken``. Routes consume this projection
    rather than reading the model or reimplementing grace semantics.
    """

    credential_id = auth.credential_id
    token = db.get(AuthToken, credential_id) if credential_id is not None else None
    if (
        token is None
        or token.token_hash != auth.credential_hash
        or token.scope != auth.scope
    ):
        raise AppError("invalid_token", status_code=401)
    state = _session_credential_state(token, now=now_utc())
    if state is None:
        raise AppError("invalid_token", status_code=401)
    return state
