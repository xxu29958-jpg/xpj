"""Desktop application-principal lifecycle operations."""

from __future__ import annotations

import hmac

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services.session_lifecycle_service import hash_secret, revoke_token_value
from app.tenants import AuthContext


def revoke_desktop_app_session(
    db: Session,
    *,
    auth: AuthContext,
    token_value: str,
) -> None:
    """Revoke the exact app credential authenticated for this request."""

    if (
        auth.scope != "app"
        or auth.credential_hash is None
        or not hmac.compare_digest(hash_secret(token_value), auth.credential_hash)
    ):
        raise AppError("invalid_token", status_code=401)
    revoked = revoke_token_value(
        db,
        token_value=token_value,
        scope="app",
    )
    if revoked != 1:
        db.rollback()
        raise AppError("invalid_token", status_code=401)
    db.commit()
