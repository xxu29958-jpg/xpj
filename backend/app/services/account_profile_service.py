"""The authenticated account owns its display name, independently of ledger roles."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account
from app.services.session_credential_lock import lock_and_revalidate_session_principal
from app.tenants import SessionPrincipal


@dataclass(frozen=True)
class AccountProfile:
    account_public_id: str
    display_name: str


def _account(db: Session, principal: SessionPrincipal, *, for_update: bool = False) -> Account:
    account = db.get(Account, principal.account_id, populate_existing=True, with_for_update=for_update)
    if account is None or account.public_id != principal.account_public_id or account.disabled_at is not None:
        raise AppError("invalid_token", status_code=401)
    return account


def read_profile(db: Session, principal: SessionPrincipal) -> AccountProfile:
    account = _account(db, principal)
    return AccountProfile(account.public_id, account.display_name)


def rename_profile(db: Session, principal: SessionPrincipal, *, display_name: str, expected_name: str) -> AccountProfile:
    name = display_name.strip()
    if not name or len(name) > 120:
        raise AppError("invalid_request", "账号名称需在 1–120 个字符之间。", status_code=422)
    lock_and_revalidate_session_principal(db, principal)
    account = _account(db, principal, for_update=True)
    # Repeating a successful assignment is harmless; a different concurrent name
    # must be shown to the person before they explicitly retry their draft.
    if account.display_name != name and account.display_name != expected_name:
        raise AppError("conflict", "账号名称已在另一处修改。这次没有覆盖；请核对当前名称后重新保存，输入已保留。", status_code=409)
    account.display_name = name
    db.commit()
    return AccountProfile(account.public_id, account.display_name)
