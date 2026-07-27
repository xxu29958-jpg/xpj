"""Desktop two-phase credential: staged pending token + recoverable activation.

Desktop pairing (and later desktop ledger-switch prepare) first stages a
short-lived ``scope='desktop_pending'`` token. That scope is in no
``allowed_scopes`` set, so every ordinary auth surface — business routes,
``/api/auth/check``, ``/api/auth/refresh``, web cookie auth — rejects it by
construction. The only way forward is ``activate_desktop_session`` with the
stable attempt proof. The ``DesktopActivationAttempt`` receipt, the advisory
lock, and the deterministic derived value mirror the session-refresh
transaction, so a response-loss replay returns the same committed activation
instead of minting a second credential.
"""

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
    DesktopActivationAttempt,
    Device,
    Ledger,
    LedgerMember,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import (
    app_token_expiry_window,
    app_token_soft_refresh_after,
    derive_desktop_activation_token,
    family_of_token,
    hash_desktop_activation_attempt_secret,
    hash_secret,
    issue_auth_token,
)
from app.services.time_service import ensure_utc, now_utc

DESKTOP_PENDING_SCOPE = "desktop_pending"
# Mirrored by the desktop Manager: `desktop/backend_manager/app_controller.py`
# constant ``_PROVISIONAL_ATTEMPT_TTL_SECONDS`` (its provisional-attempt
# deadline MUST stay >= this TTL, or the client could retire a still-live
# proof). Change only together; pinned by tests on both sides.
DESKTOP_PENDING_TOKEN_TTL_SECONDS = 300
DESKTOP_PLATFORM = "desktop"


@dataclass(frozen=True)
class DesktopActivationResult:
    session_token: str
    activation_attempt_id: str
    account_public_id: str
    device_public_id: str
    ledger_id: str
    expires_at: datetime | None
    soft_refresh_after: datetime | None
    # True = this call performed the activation; False = canonical replay of
    # the already-committed activation after a response loss.
    activated: bool


class DesktopActivationPersistenceError(RuntimeError):
    """A staged credential was not visible inside its issuing transaction."""


def _invalid_activation() -> AppError:
    return AppError("invalid_token", status_code=401)


def _proof(secret: str, attempt_id: str) -> tuple[str, str]:
    try:
        return (
            hash_desktop_activation_attempt_secret(secret),
            derive_desktop_activation_token(secret, attempt_id),
        )
    except ValueError as exc:
        raise _invalid_activation() from exc


def _principal_is_live(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
) -> bool:
    """Validate the desktop Account/Device/Ledger/membership under one lock."""

    row = db.scalar(
        select(Device.id)
        .join(Account, Account.id == Device.account_id)
        .join(Ledger, Ledger.ledger_id == ledger_id)
        .join(
            LedgerMember,
            (LedgerMember.ledger_id == ledger_id) & (LedgerMember.account_id == account_id),
        )
        .where(Account.id == account_id)
        .where(Account.disabled_at.is_(None))
        .where(Device.id == device_id)
        .where(Device.revoked_at.is_(None))
        .where(Device.platform == DESKTOP_PLATFORM)
        .where(Ledger.archived_at.is_(None))
        .where(LedgerMember.disabled_at.is_(None))
        .with_for_update()
    )
    return row is not None


def stage_desktop_pending_token(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    attempt_public_id: str,
    activation_secret: str,
    previous_token_id: int | None = None,
    issued_at: datetime | None = None,
) -> AuthToken:
    """Stage one ``desktop_pending`` credential + its activation receipt.

    A second staging for the same principal supersedes the first (hard
    revoke, no grace): superseded pending credentials never revive.
    """

    issued_at = issued_at or now_utc()
    token_value = derive_desktop_activation_token(activation_secret, attempt_public_id)
    expires_at = issued_at + timedelta(seconds=DESKTOP_PENDING_TOKEN_TTL_SECONDS)
    stale_rows = db.scalars(
        select(AuthToken)
        .where(AuthToken.account_id == account_id)
        .where(AuthToken.device_id == device_id)
        .where(AuthToken.ledger_id == ledger_id)
        .where(AuthToken.scope == DESKTOP_PENDING_SCOPE)
        .where(AuthToken.revoked_at.is_(None))
        .with_for_update()
    ).all()
    for stale in stale_rows:
        stale.revoked_at = issued_at
        stale.grace_until = None
    db.flush()
    issue_auth_token(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        scope=DESKTOP_PENDING_SCOPE,
        expires_at=expires_at,
        token_value=token_value,
    )
    token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value)).limit(1))
    if token is None:
        raise DesktopActivationPersistenceError("staged desktop credential was not persisted")
    db.add(
        DesktopActivationAttempt(
            public_id=attempt_public_id,
            token_id=token.id,
            previous_token_id=previous_token_id,
            account_id=account_id,
            device_id=device_id,
            ledger_id=ledger_id,
            secret_hash=hash_desktop_activation_attempt_secret(activation_secret),
            activated_at=None,
            expires_at=expires_at,
            last_issued_at=None,
            created_at=issued_at,
        )
    )
    db.flush()
    return token


def find_live_pending_token(db: Session, *, session_token_hash: str) -> AuthToken | None:
    """Return the still-usable staged credential behind one token hash, if any."""

    token = db.scalar(select(AuthToken).where(AuthToken.token_hash == session_token_hash).with_for_update().limit(1))
    checked_at = now_utc()
    token_expires_at = ensure_utc(token.expires_at) if token and token.expires_at else None
    if (
        token is None
        or token.scope != DESKTOP_PENDING_SCOPE
        or token.revoked_at is not None
        or token_expires_at is None
        or token_expires_at <= checked_at
    ):
        return None
    return token


def _revoke_dead_staged(token: AuthToken | None, checked_at: datetime, db: Session) -> None:
    """Fail closed: a malformed/expired staged row is revoked in place.

    Commits like the lazy-revoke path in ``_auth``: the refusal must be
    durable even though the endpoint returns 401 and never commits itself.
    """

    if token is not None and token.revoked_at is None and token.scope == DESKTOP_PENDING_SCOPE:
        token.revoked_at = checked_at
        token.grace_until = None
        db.commit()


def _load_live_previous_token(
    db: Session,
    *,
    attempt: DesktopActivationAttempt,
    staged_token: AuthToken,
    previous_token_value: str | None,
    checked_at: datetime,
) -> AuthToken | None:
    """Validate the optional predecessor possession proof.

    A long-dead (revoked past grace) or expired predecessor is a no-op, never
    a blocker. A live or grace-window predecessor must be an ``app`` token on
    a desktop device bound to the SAME account and ledger as the staged
    credential — a foreign token is refused (401) and never revoked, so it
    can never be mis-registered into this activation's lineage.
    """

    if not previous_token_value:
        return None
    previous = db.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_secret(previous_token_value)).with_for_update().limit(1)
    )
    if previous is None:
        return None
    if previous.id == staged_token.id:
        raise AppError("desktop_identity_rotation_required", status_code=409)
    previous_expires_at = ensure_utc(previous.expires_at) if previous.expires_at else None
    if previous_expires_at is not None and previous_expires_at <= checked_at:
        return None
    if previous.revoked_at is not None:
        # Revocation inside the rotation grace window is still an in-flight
        # predecessor (its refresh lineage must be closed); past grace it is
        # just history and a no-op.
        grace_until = ensure_utc(previous.grace_until) if previous.grace_until else None
        if grace_until is None or grace_until <= checked_at:
            return None
    if previous.scope != "app":
        return None
    # Identity binding: the predecessor must share the staged credential's
    # account and ledger. Anything else is a foreign credential, not a
    # predecessor — refuse without touching it.
    if previous.account_id != attempt.account_id or previous.ledger_id != attempt.ledger_id:
        raise _invalid_activation()
    previous_device = db.get(Device, previous.device_id)
    if previous_device is None or (previous_device.platform or "") != DESKTOP_PLATFORM:
        raise _invalid_activation()
    return previous


def _recover_committed_activation(
    db: Session,
    *,
    attempt: DesktopActivationAttempt,
    token: AuthToken | None,
    token_value: str,
    checked_at: datetime,
) -> DesktopActivationResult:
    """Replay the exact committed activation after a response loss."""

    token_expires_at = ensure_utc(token.expires_at) if token and token.expires_at else None
    if (
        token is None
        or token.scope != "app"
        or token.revoked_at is not None
        or (token_expires_at is not None and token_expires_at <= checked_at)
        or token.account_id != attempt.account_id
        or token.device_id != attempt.device_id
        or token.ledger_id != attempt.ledger_id
        or not hmac.compare_digest(token.token_hash, hash_secret(token_value))
        or not _principal_is_live(
            db,
            account_id=attempt.account_id,
            device_id=attempt.device_id,
            ledger_id=attempt.ledger_id,
        )
    ):
        raise _invalid_activation()
    attempt.last_issued_at = checked_at
    db.flush()
    account = db.get(Account, attempt.account_id)
    device = db.get(Device, attempt.device_id)
    return DesktopActivationResult(
        session_token=token_value,
        activation_attempt_id=attempt.public_id,
        account_public_id=account.public_id if account else "",
        device_public_id=device.public_id if device else "",
        ledger_id=attempt.ledger_id,
        expires_at=token_expires_at,
        soft_refresh_after=app_token_soft_refresh_after(token_expires_at),
        activated=False,
    )


def _supersede_predecessors(
    db: Session,
    *,
    attempt: DesktopActivationAttempt,
    staged_token: AuthToken,
    previous: AuthToken | None,
    checked_at: datetime,
) -> None:
    """Supersede same-slot predecessors with rotation grace + record lineage.

    The explicit header proof plus any live app token occupying the unique
    partial index slot are revoked with the same rotation grace refresh uses.
    A switch-staged attempt additionally names its source credential
    (``previous_token_id`` from prepare): if that source was rotated through
    ``/api/auth/refresh`` between prepare and activation, its live refresh
    family (A2, A3, …) is closed atomically here. Two honest limits: the
    close is grace-based, so inside the grace window the general API surface
    still accepts a graced A2 (exactly like a refreshed session); and when
    activation presents an explicit predecessor header, the header family is
    the one closed and the staged source family is left alone (the
    ``previous is None`` guard below). The unauthenticated replay contract
    is untouched: this runs once inside the committing transaction; a
    response-loss replay re-reads the already-committed state.
    """

    grace_seconds = max(get_settings().app_token_rotation_grace_seconds, 0)
    grace_until = checked_at + timedelta(seconds=grace_seconds) if grace_seconds > 0 else None
    staged_previous_id = attempt.previous_token_id
    predecessors = db.scalars(
        select(AuthToken)
        .where(AuthToken.account_id == attempt.account_id)
        .where(AuthToken.device_id == attempt.device_id)
        .where(AuthToken.ledger_id == attempt.ledger_id)
        .where(AuthToken.scope == "app")
        .where(AuthToken.revoked_at.is_(None))
        .where(AuthToken.id != staged_token.id)
        .with_for_update()
    ).all()
    superseded_ids: set[int] = set()
    for predecessor in predecessors:
        predecessor.revoked_at = checked_at
        predecessor.grace_until = grace_until
        superseded_ids.add(predecessor.id)
    if previous is not None:
        # Close the whole predecessor lineage: if the presented credential was
        # already refreshed, its family head (the live replacement) must not
        # survive the activation as a second authorized family.
        family_head: AuthToken | None = None
        for member in family_of_token(db, token=previous):
            if member.id == staged_token.id:
                continue
            if member.revoked_at is None:
                member.revoked_at = checked_at
                member.grace_until = grace_until
                superseded_ids.add(member.id)
                family_head = member
        attempt.previous_token_id = (family_head or previous).id
    elif predecessors:
        attempt.previous_token_id = predecessors[0].id
    if staged_previous_id is not None and previous is None:
        # The switch-staged source family (prepare-time predecessor): close
        # A's refresh descendants (A2…) alongside A, atomically with B's
        # promotion. The header case above already closes its own family, so
        # this only runs where no explicit predecessor proof was presented.
        staged_previous = db.get(AuthToken, staged_previous_id)
        if staged_previous is not None:
            for member in family_of_token(db, token=staged_previous):
                if member.id == staged_token.id or member.revoked_at is not None:
                    continue
                member.revoked_at = checked_at
                member.grace_until = grace_until
                superseded_ids.add(member.id)


def _activate_staged_token(
    db: Session,
    *,
    attempt: DesktopActivationAttempt,
    token: AuthToken | None,
    token_value: str,
    previous_token_value: str | None,
    checked_at: datetime,
) -> DesktopActivationResult:
    token_expires_at = ensure_utc(token.expires_at) if token and token.expires_at else None
    if (
        token is None
        or token.scope != DESKTOP_PENDING_SCOPE
        or token.revoked_at is not None
        or token_expires_at is None
        or token_expires_at <= checked_at
        or token.account_id != attempt.account_id
        or token.device_id != attempt.device_id
        or token.ledger_id != attempt.ledger_id
        or not hmac.compare_digest(token.token_hash, hash_secret(token_value))
    ):
        _revoke_dead_staged(token, checked_at, db)
        raise _invalid_activation()
    if not _principal_is_live(
        db,
        account_id=attempt.account_id,
        device_id=attempt.device_id,
        ledger_id=attempt.ledger_id,
    ):
        raise _invalid_activation()
    previous = _load_live_previous_token(
        db,
        attempt=attempt,
        staged_token=token,
        previous_token_value=previous_token_value,
        checked_at=checked_at,
    )

    _supersede_predecessors(
        db,
        attempt=attempt,
        staged_token=token,
        previous=previous,
        checked_at=checked_at,
    )

    # Promote the staged credential in place: same value, real session scope.
    expiry = app_token_expiry_window(checked_at)
    token.scope = "app"
    token.expires_at = expiry.expires_at
    token.last_used_at = checked_at
    device = db.get(Device, attempt.device_id)
    if device is not None:
        device.last_seen_at = checked_at
    attempt.activated_at = checked_at
    attempt.last_issued_at = checked_at
    db.flush()
    account = db.get(Account, attempt.account_id)
    return DesktopActivationResult(
        session_token=token_value,
        activation_attempt_id=attempt.public_id,
        account_public_id=account.public_id if account else "",
        device_public_id=device.public_id if device else "",
        ledger_id=attempt.ledger_id,
        expires_at=expiry.expires_at,
        soft_refresh_after=expiry.soft_refresh_after,
        activated=True,
    )


def activate_desktop_session(
    db: Session,
    *,
    activation_attempt_id: str,
    activation_attempt_secret: str,
    previous_token_value: str | None = None,
) -> DesktopActivationResult:
    """Activate once or replay the exact committed result after response loss."""

    secret_hash, token_value = _proof(activation_attempt_secret, activation_attempt_id)
    lock_bootstrap_owner_transaction(db)
    attempt = db.scalar(
        select(DesktopActivationAttempt)
        .where(DesktopActivationAttempt.public_id == activation_attempt_id)
        .with_for_update()
        .limit(1)
    )
    if attempt is None or not hmac.compare_digest(attempt.secret_hash, secret_hash):
        raise _invalid_activation()
    checked_at = now_utc()
    token = db.get(AuthToken, attempt.token_id, with_for_update=True)
    attempt_expires_at = ensure_utc(attempt.expires_at)
    if (
        attempt.activated_at is None
        and attempt_expires_at is not None
        and attempt_expires_at <= checked_at
    ):
        # Fail closed: an expired staged credential never activates.
        _revoke_dead_staged(token, checked_at, db)
        raise _invalid_activation()
    if attempt.activated_at is not None:
        return _recover_committed_activation(
            db,
            attempt=attempt,
            token=token,
            token_value=token_value,
            checked_at=checked_at,
        )
    return _activate_staged_token(
        db,
        attempt=attempt,
        token=token,
        token_value=token_value,
        previous_token_value=previous_token_value,
        checked_at=checked_at,
    )
