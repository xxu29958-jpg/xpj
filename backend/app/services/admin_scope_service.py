from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, Ledger, LedgerMember
from app.services import permission_service
from app.services.ledger_service import managed_ledger_ids_for_account
from app.services.session_credential_lock import (
    lock_and_revalidate_credential_mint_context,
)
from app.tenants import AuthContext


def manageable_ledger_ids(db: Session, auth: AuthContext) -> set[str]:
    """Ledgers this admin token's account can manage as an active owner.

    Admin-scope proves that the token is a maintenance credential. It does not
    grant authority over every ledger the account can merely view or write.
    """

    permission_service.require_admin_maintenance(auth)
    return managed_ledger_ids_for_account(db, account_id=auth.account_id)


def require_admin_manages_current_ledger(db: Session, auth: AuthContext) -> AuthContext:
    if auth.ledger_id not in manageable_ledger_ids(db, auth):
        raise AppError("permission_denied", status_code=403)
    return auth


def lock_and_resolve_mutation_ledger_ids(
    db: Session,
    *,
    auth: AuthContext | None,
    actor_account_id: int | None,
    requested_ledger_ids: set[str] | None,
) -> set[str] | None:
    """Lock, revalidate, then resolve the actor's current owner scope.

    Route-level ledger sets are request hints, not authorization evidence: an
    owner transfer or credential revocation may commit after authentication but
    before the mutation starts. Network callers pass ``auth``; the loopback
    Owner Console passes its resolved account id. ``None`` for both is reserved
    for explicit trusted maintenance callers that intentionally operate without
    a ledger scope.
    """

    locked_auth = lock_and_revalidate_credential_mint_context(db, auth)
    if locked_auth is not None:
        if actor_account_id is not None and actor_account_id != locked_auth.account_id:
            raise AppError("invalid_token", status_code=401)
        actor_account_id = locked_auth.account_id
    if actor_account_id is None:
        return requested_ledger_ids

    current_ledger_ids = set(
        db.scalars(
            select(Ledger.ledger_id)
            .join(
                LedgerMember,
                LedgerMember.ledger_id == Ledger.ledger_id,
            )
            .join(Account, Account.id == LedgerMember.account_id)
            .where(Account.id == actor_account_id)
            .where(Account.disabled_at.is_(None))
            .where(Ledger.owner_account_id == actor_account_id)
            .where(Ledger.archived_at.is_(None))
            .where(LedgerMember.role == "owner")
            .where(LedgerMember.disabled_at.is_(None))
        )
    )
    if requested_ledger_ids is None:
        return current_ledger_ids
    return current_ledger_ids.intersection(requested_ledger_ids)
