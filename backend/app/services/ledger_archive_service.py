"""Owner-authorized reversible ledger archive lifecycle."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Ledger, LedgerAuditLog, LedgerMember
from app.services.identity_service._bootstrap_exposure_guard import (
    assert_bootstrap_sensitive_mutation_allowed,
)
from app.services.session_credential_lock import lock_and_revalidate_mutation_actor
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID, AuthContext

AUDIT_LEDGER_ARCHIVED = "ledger_archived"
AUDIT_LEDGER_UNARCHIVED = "ledger_unarchived"


def find_owner_account_id_for_ledger(db: Session, *, ledger_id: str) -> int | None:
    """Return the active owner's account id, or ``None``."""
    return db.scalar(
        select(LedgerMember.account_id)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.role == "owner")
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )


def _authorize_ledger_owner(db: Session, *, ledger_id: str, actor_account_id: int) -> Ledger:
    ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id).limit(1))
    if ledger is None:
        raise AppError("ledger_not_found", status_code=404)
    if find_owner_account_id_for_ledger(db, ledger_id=ledger_id) != actor_account_id:
        raise AppError("ledger_forbidden", status_code=403)
    return ledger


def _record_ledger_audit(db: Session, *, ledger_id: str, action: str, actor_account_id: int) -> None:
    db.add(
        LedgerAuditLog(
            ledger_id=ledger_id,
            action=action,
            actor_account_id=actor_account_id,
            resource_type="ledger",
            resource_public_id=ledger_id,
            result="success",
        )
    )


def archive_ledger(
    db: Session,
    *,
    ledger_id: str,
    actor_account_id: int,
    auth: AuthContext | None,
) -> bool:
    """Archive an owner-managed ledger; return whether active state changed."""
    lock_and_revalidate_mutation_actor(
        db,
        auth,
        actor_account_id=actor_account_id,
        ledger_id=ledger_id,
    )
    assert_bootstrap_sensitive_mutation_allowed(
        db,
        actor_account_id=actor_account_id,
        ledger_ids={ledger_id},
    )
    ledger = _authorize_ledger_owner(db, ledger_id=ledger_id, actor_account_id=actor_account_id)
    if ledger.ledger_id == DEFAULT_TENANT_ID:
        raise AppError("cannot_archive_default_ledger", status_code=409)
    flipped = (
        db.execute(
            update(Ledger)
            .where(Ledger.ledger_id == ledger_id, Ledger.archived_at.is_(None))
            .values(archived_at=now_utc())
        ).rowcount
        == 1
    )
    if not flipped:
        db.rollback()
        return False
    _record_ledger_audit(
        db,
        ledger_id=ledger_id,
        action=AUDIT_LEDGER_ARCHIVED,
        actor_account_id=actor_account_id,
    )
    db.commit()
    return True


def unarchive_ledger(
    db: Session,
    *,
    ledger_id: str,
    actor_account_id: int,
    auth: AuthContext | None,
) -> bool:
    """Restore an owner-managed ledger; return whether archived state changed."""
    lock_and_revalidate_mutation_actor(
        db,
        auth,
        actor_account_id=actor_account_id,
        ledger_id=ledger_id,
    )
    assert_bootstrap_sensitive_mutation_allowed(
        db,
        actor_account_id=actor_account_id,
        ledger_ids={ledger_id},
    )
    _authorize_ledger_owner(db, ledger_id=ledger_id, actor_account_id=actor_account_id)
    flipped = (
        db.execute(
            update(Ledger)
            .where(Ledger.ledger_id == ledger_id, Ledger.archived_at.is_not(None))
            .values(archived_at=None)
        ).rowcount
        == 1
    )
    if not flipped:
        db.rollback()
        return False
    _record_ledger_audit(
        db,
        ledger_id=ledger_id,
        action=AUDIT_LEDGER_UNARCHIVED,
        actor_account_id=actor_account_id,
    )
    db.commit()
    return True
