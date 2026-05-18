from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import LedgerMember
from app.tenants import AuthContext


def manageable_ledger_ids(db: Session, auth: AuthContext) -> set[str]:
    """Ledgers this admin token's account can manage as an active owner.

    Admin-scope proves that the token is a maintenance credential. It does not
    grant authority over every ledger the account can merely view or write.
    """

    if auth.scope != "admin":
        raise AppError("invalid_token", status_code=401)
    return set(
        db.scalars(
            select(LedgerMember.ledger_id)
            .where(LedgerMember.account_id == auth.account_id)
            .where(LedgerMember.role == "owner")
            .where(LedgerMember.disabled_at.is_(None))
        ).all()
    )


def require_admin_manages_current_ledger(db: Session, auth: AuthContext) -> AuthContext:
    if auth.ledger_id not in manageable_ledger_ids(db, auth):
        raise AppError("permission_denied", status_code=403)
    return auth
