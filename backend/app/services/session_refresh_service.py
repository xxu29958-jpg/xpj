"""Recoverable app-session refresh transaction."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    Device,
    SessionRefreshAttempt,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import (
    app_token_expiry_window,
    derive_session_refresh_token,
    hash_secret,
    hash_session_refresh_attempt_secret,
    issue_auth_token,
)
from app.services.time_service import ensure_utc, now_utc


@dataclass(frozen=True)
class SessionRefreshResult:
    session_token: str
    refresh_attempt_id: str
    expires_at: datetime
    soft_refresh_after: datetime | None


@dataclass(frozen=True)
class LegacySessionRefreshResult:
    session_token: str
    expires_at: datetime
    soft_refresh_after: datetime | None


class SessionRefreshPersistenceError(RuntimeError):
    """A replacement credential was not visible inside its issuing transaction."""


def _invalid_refresh() -> AppError:
    return AppError("invalid_token", status_code=401)


def _proof(secret: str, attempt_id: str) -> tuple[str, str]:
    try:
        return (
            hash_session_refresh_attempt_secret(secret),
            derive_session_refresh_token(secret, attempt_id),
        )
    except ValueError as exc:
        raise _invalid_refresh() from exc


def _session_principal_is_active(db: Session, token: AuthToken) -> bool:
    """Validate the Account/Device session independently of its ledger default."""

    row = db.scalar(
        select(Device.id)
        .join(Account, Account.id == Device.account_id)
        .where(Account.id == token.account_id)
        .where(Account.disabled_at.is_(None))
        .where(Device.id == token.device_id)
        .where(Device.revoked_at.is_(None))
    )
    return row is not None


def _recover_committed_refresh(
    db: Session,
    *,
    source: AuthToken,
    attempt: SessionRefreshAttempt,
    attempt_id: str,
    secret_hash: str,
    replacement_value: str,
    checked_at: datetime,
) -> SessionRefreshResult:
    if (
        attempt.public_id != attempt_id
        or attempt.source_token_id != source.id
        or not hmac.compare_digest(attempt.secret_hash, secret_hash)
        or ensure_utc(attempt.expires_at) <= checked_at
    ):
        raise _invalid_refresh()
    replacement = db.get(AuthToken, attempt.replacement_token_id)
    replacement_expires_at = ensure_utc(replacement.expires_at) if replacement else None
    if (
        replacement is None
        or replacement.scope != "app"
        or replacement.revoked_at is not None
        or replacement_expires_at is None
        or replacement_expires_at <= checked_at
        or replacement.account_id != source.account_id
        or replacement.device_id != source.device_id
        or replacement.ledger_id != source.ledger_id
        or not hmac.compare_digest(replacement.token_hash, hash_secret(replacement_value))
        or not _session_principal_is_active(db, replacement)
    ):
        raise _invalid_refresh()
    attempt.last_issued_at = checked_at
    return SessionRefreshResult(
        session_token=replacement_value,
        refresh_attempt_id=attempt.public_id,
        expires_at=replacement_expires_at,
        soft_refresh_after=ensure_utc(attempt.session_soft_refresh_after),
    )


def _load_source_token(db: Session, source_token_value: str) -> AuthToken:
    source = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(source_token_value)).limit(1))
    if source is None or source.scope != "app":
        raise _invalid_refresh()
    return source


def refresh_legacy_app_session(
    db: Session,
    *,
    source_token_value: str,
) -> LegacySessionRefreshResult:
    """Keep one N-1 app session alive without an unrecoverable rotation."""

    lock_bootstrap_owner_transaction(db)
    source = _load_source_token(db, source_token_value)
    refreshed_at = now_utc()
    source_expires_at = ensure_utc(source.expires_at)
    if (
        source.revoked_at is not None
        or source_expires_at is None
        or source_expires_at <= refreshed_at
        or not _session_principal_is_active(db, source)
    ):
        raise _invalid_refresh()
    expiry = app_token_expiry_window(refreshed_at)
    if expiry.expires_at is None:
        raise AppError("invalid_request", "当前服务未启用会话续期。", status_code=409)
    source.expires_at = expiry.expires_at
    source.last_used_at = refreshed_at
    db.flush()
    return LegacySessionRefreshResult(
        session_token=source_token_value,
        expires_at=expiry.expires_at,
        soft_refresh_after=expiry.soft_refresh_after,
    )


def _load_committed_attempt(
    db: Session,
    *,
    source: AuthToken,
    refresh_attempt_id: str,
) -> SessionRefreshAttempt | None:
    requested_attempt = db.scalar(
        select(SessionRefreshAttempt).where(SessionRefreshAttempt.public_id == refresh_attempt_id).limit(1)
    )
    source_attempt = db.scalar(
        select(SessionRefreshAttempt).where(SessionRefreshAttempt.source_token_id == source.id).limit(1)
    )
    return requested_attempt or source_attempt


def _rotate_new_refresh(
    db: Session,
    *,
    source: AuthToken,
    replacement_value: str,
    refresh_attempt_id: str,
    secret_hash: str,
    checked_at: datetime,
) -> SessionRefreshResult:
    source_expires_at = ensure_utc(source.expires_at)
    if (
        source.revoked_at is not None
        or source_expires_at is None
        or source_expires_at <= checked_at
        or not _session_principal_is_active(db, source)
    ):
        raise _invalid_refresh()

    expiry = app_token_expiry_window(checked_at)
    if expiry.expires_at is None:
        raise AppError("invalid_request", "当前服务未启用会话轮换。", status_code=409)
    grace_seconds = max(get_settings().app_token_rotation_grace_seconds, 0)
    source.revoked_at = checked_at
    source.grace_until = checked_at + timedelta(seconds=grace_seconds) if grace_seconds > 0 else None
    db.flush()
    issue_auth_token(
        db,
        account_id=source.account_id,
        device_id=source.device_id,
        ledger_id=source.ledger_id,
        scope="app",
        expires_at=expiry.expires_at,
        token_value=replacement_value,
    )
    replacement = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(replacement_value)).limit(1))
    if replacement is None:
        raise SessionRefreshPersistenceError("session refresh replacement was not persisted")
    db.add(
        SessionRefreshAttempt(
            public_id=refresh_attempt_id,
            source_token_id=source.id,
            replacement_token_id=replacement.id,
            secret_hash=secret_hash,
            session_soft_refresh_after=expiry.soft_refresh_after,
            expires_at=expiry.expires_at,
            last_issued_at=checked_at,
            created_at=checked_at,
        )
    )
    db.flush()
    return SessionRefreshResult(
        session_token=replacement_value,
        refresh_attempt_id=refresh_attempt_id,
        expires_at=expiry.expires_at,
        soft_refresh_after=expiry.soft_refresh_after,
    )


def refresh_or_recover_app_session(
    db: Session,
    *,
    source_token_value: str,
    refresh_attempt_id: str,
    refresh_attempt_secret: str,
) -> SessionRefreshResult:
    """Rotate once or replay the exact committed result after response loss."""

    secret_hash, replacement_value = _proof(
        refresh_attempt_secret,
        refresh_attempt_id,
    )
    lock_bootstrap_owner_transaction(db)
    source = _load_source_token(db, source_token_value)
    checked_at = now_utc()
    committed = _load_committed_attempt(
        db,
        source=source,
        refresh_attempt_id=refresh_attempt_id,
    )
    if committed is not None:
        return _recover_committed_refresh(
            db,
            source=source,
            attempt=committed,
            attempt_id=refresh_attempt_id,
            secret_hash=secret_hash,
            replacement_value=replacement_value,
            checked_at=checked_at,
        )
    return _rotate_new_refresh(
        db,
        source=source,
        replacement_value=replacement_value,
        refresh_attempt_id=refresh_attempt_id,
        secret_hash=secret_hash,
        checked_at=checked_at,
    )
