"""Owner/ledger/membership seeding + ledger queries."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError, DataIntegrityError
from app.models import Account, AuthToken, Ledger, LedgerMember
from app.services import permission_service
from app.services.identity_service._legacy_compat import _legacy_ledgers_from_config
from app.services.identity_service._models import DEFAULT_ACCOUNT_NAME
from app.tenants import DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME, TENANT_ID_PATTERN


def _clean_name(value: str | None, fallback: str) -> str:
    cleaned = (value or "").strip()
    return cleaned or fallback


def _owner_account(db: Session, display_name: str = DEFAULT_ACCOUNT_NAME) -> Account:
    account = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
    if account is not None:
        return account
    account = Account(display_name=_clean_name(display_name, DEFAULT_ACCOUNT_NAME))
    db.add(account)
    db.flush()
    return account


def _ledger_by_id(db: Session, ledger_id: str) -> Ledger | None:
    return db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id).limit(1))


def _ensure_ledger(db: Session, *, ledger_id: str, name: str, owner_account: Account) -> Ledger:
    if not TENANT_ID_PATTERN.fullmatch(ledger_id):
        raise DataIntegrityError(f"Invalid legacy data: ledger_id contains unsupported value: {ledger_id}")
    ledger = _ledger_by_id(db, ledger_id)
    if ledger is None:
        ledger = Ledger(
            ledger_id=ledger_id,
            name=_clean_name(name, ledger_id),
            owner_account_id=owner_account.id,
        )
        db.add(ledger)
        db.flush()
    else:
        if not ledger.name:
            ledger.name = _clean_name(name, ledger_id)
        if not ledger.owner_account_id:
            ledger.owner_account_id = owner_account.id
    _ensure_membership(db, ledger.ledger_id, owner_account.id, "owner")
    return ledger


def _ensure_membership(db: Session, ledger_id: str, account_id: int, role: str) -> LedgerMember:
    if not permission_service.is_valid_role(role):
        raise AppError("ledger_member_role_invalid", status_code=422)
    member = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == account_id)
        .limit(1)
    )
    if member is not None:
        if member.disabled_at is None and member.role != role:
            member.role = role
        return member
    member = LedgerMember(ledger_id=ledger_id, account_id=account_id, role=role)
    db.add(member)
    db.flush()
    return member


def ensure_identity_seed(db: Session) -> None:
    owner = _owner_account(db)
    seen: set[str] = set()
    for legacy_tenant in _legacy_ledgers_from_config():
        seen.add(legacy_tenant.id)
        _ensure_ledger(db, ledger_id=legacy_tenant.id, name=legacy_tenant.name, owner_account=owner)

    ledger_ids_from_data = set(
        db.scalars(select(func.distinct(Ledger.ledger_id)))
    )
    for ledger_id in sorted(ledger_ids_from_data - seen):
        ledger = _ledger_by_id(db, ledger_id)
        if ledger is not None:
            _ensure_membership(db, ledger.ledger_id, owner.id, "owner")


def ensure_identity_for_existing_ledger_ids(db: Session, ledger_ids: set[str]) -> None:
    owner = _owner_account(db)
    legacy_names = {tenant.id: tenant.name for tenant in _legacy_ledgers_from_config()}
    for ledger_id in sorted(ledger_ids):
        _ensure_ledger(
            db,
            ledger_id=ledger_id,
            name=legacy_names.get(ledger_id, DEFAULT_TENANT_NAME if ledger_id == DEFAULT_TENANT_ID else ledger_id),
            owner_account=owner,
        )


def ledger_ids(db: Session) -> list[str]:
    return list(db.scalars(select(Ledger.ledger_id).where(Ledger.archived_at.is_(None)).order_by(Ledger.id.asc())))


def active_auth_token_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(AuthToken).where(AuthToken.revoked_at.is_(None))) or 0)
