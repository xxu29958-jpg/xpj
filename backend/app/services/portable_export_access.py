"""Read authority for a selected portable package, including an owned archive.

The returned context belongs only to the export queries. Ordinary app and Web
authentication still rejects archived ledgers; no session or ledger is switched.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AuthToken, Ledger, LedgerMember
from app.services.ledger_contracts import LedgerSummary
from app.services.ledger_service import list_archived_ledgers_for_account, list_ledgers_for_account
from app.services.session_credential_lock import revalidate_session_principal
from app.tenants import AuthContext, SessionPrincipal


def _export_principal(db: Session, principal: SessionPrincipal) -> SessionPrincipal:
    if principal.scope != "app":
        raise AppError("invalid_token", status_code=401)
    return revalidate_session_principal(db, principal)


def list_portable_ledgers(db: Session, principal: SessionPrincipal) -> list[LedgerSummary]:
    current = _export_principal(db, principal)
    return [*list_ledgers_for_account(db, account_id=current.account_id),
            *list_archived_ledgers_for_account(db, account_id=current.account_id)]


def resolve_portable_export_context(
    db: Session, principal: SessionPrincipal, *, ledger_id: str | None = None,
) -> AuthContext:
    current = _export_principal(db, principal)
    selected = ledger_id or db.scalar(select(AuthToken.ledger_id).where(
        AuthToken.id == current.credential_id, AuthToken.token_hash == current.credential_hash))
    row = db.execute(select(Ledger, LedgerMember.role)
        .join(LedgerMember, LedgerMember.ledger_id == Ledger.ledger_id)
        .where(Ledger.ledger_id == selected, LedgerMember.account_id == current.account_id,
            LedgerMember.disabled_at.is_(None),
            or_(Ledger.archived_at.is_(None), LedgerMember.role == "owner"))
        .limit(1)).first()
    if row is None:
        raise AppError("ledger_forbidden", status_code=403)
    ledger, role = row
    return AuthContext(account_id=current.account_id, account_public_id=current.account_public_id,
        account_name=current.account_name, device_id=current.device_id, device_public_id=current.device_public_id,
        device_name=current.device_name, ledger_id=ledger.ledger_id, ledger_name=ledger.name, role=str(role),
        scope=current.scope, credential_id=current.credential_id, credential_hash=current.credential_hash)


def revalidate_portable_export_context(db: Session, auth: AuthContext) -> AuthContext:
    if auth.credential_id is None or not auth.credential_hash:
        raise AppError("invalid_token", status_code=401)
    principal = SessionPrincipal(account_id=auth.account_id, account_public_id=auth.account_public_id,
        account_name=auth.account_name, device_id=auth.device_id, device_public_id=auth.device_public_id,
        device_name=auth.device_name, scope=auth.scope,
        credential_id=auth.credential_id, credential_hash=auth.credential_hash)
    current = resolve_portable_export_context(db, principal, ledger_id=auth.ledger_id)
    if current.role != auth.role:
        raise AppError("permission_denied", status_code=403)
    return current
