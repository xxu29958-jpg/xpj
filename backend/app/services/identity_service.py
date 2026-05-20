from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hmac import compare_digest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError, DataIntegrityError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember, PairingCode, UploadLink
from app.services import permission_service
from app.services.session_lifecycle_service import (
    consume_pairing_code,
    hash_pairing_code,
    hash_secret,
    issue_auth_token,
    issue_upload_link,
    new_pairing_code,
    new_session_token as new_session_token,
    new_upload_key as new_upload_key,
)
from app.services.time_service import ensure_utc, now_utc, to_iso
from app.tenants import AuthContext, DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME, TENANT_ID_PATTERN, Tenant, configured_tenants


DEFAULT_ACCOUNT_NAME = "我"
DEFAULT_BOOTSTRAP_DEVICE_NAME = "Windows 后端"
PAIRING_CODE_TTL_MINUTES = 15
PAIRING_MAX_FAILED_ATTEMPTS = 20
PAIRING_ATTEMPT_WINDOW = timedelta(minutes=10)

_pairing_failures_by_remote: dict[str, list[datetime]] = {}


@dataclass(frozen=True)
class BootstrapResult:
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    admin_token: str
    upload_key: str
    upload_url_path: str
    pairing_code: str
    pairing_expires_at: str


@dataclass(frozen=True)
class PairingResult:
    session_token: str
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str


@dataclass(frozen=True)
class PairingCodeResult:
    pairing_code: str
    ledger_name: str
    expires_at: str

def _remote_attempt_key(remote_id: str | None) -> str:
    return (remote_id or "unknown").strip() or "unknown"


def _active_pairing_failures(remote_id: str | None, now: datetime) -> list[datetime]:
    key = _remote_attempt_key(remote_id)
    cutoff = now - PAIRING_ATTEMPT_WINDOW
    failures = [failed_at for failed_at in _pairing_failures_by_remote.get(key, []) if failed_at > cutoff]
    if failures:
        _pairing_failures_by_remote[key] = failures
    else:
        _pairing_failures_by_remote.pop(key, None)
    return failures


def _check_pairing_attempt_limit(remote_id: str | None) -> None:
    if len(_active_pairing_failures(remote_id, now_utc())) >= PAIRING_MAX_FAILED_ATTEMPTS:
        raise AppError("invalid_pairing_code", "绑定码尝试次数过多，请稍后再试。", status_code=429)


def _record_pairing_failure(remote_id: str | None) -> None:
    now = now_utc()
    key = _remote_attempt_key(remote_id)
    failures = _active_pairing_failures(remote_id, now)
    failures.append(now)
    _pairing_failures_by_remote[key] = failures


def _clear_pairing_failures(remote_id: str | None) -> None:
    _pairing_failures_by_remote.pop(_remote_attempt_key(remote_id), None)


def _reject_pairing(remote_id: str | None, error: str, status_code: int) -> None:
    _record_pairing_failure(remote_id)
    raise AppError(error, status_code=status_code)


def _legacy_token_values(kind: str) -> set[str]:
    settings = get_settings()
    values: set[str] = set()
    if kind == "app" and settings.app_token:
        values.add(settings.app_token)
    if kind == "upload" and settings.upload_token:
        values.add(settings.upload_token)
    for tenant in configured_tenants():
        if kind == "app" and tenant.app_token:
            values.add(tenant.app_token)
        if kind == "upload" and tenant.upload_token:
            values.add(tenant.upload_token)
    return values


def is_legacy_app_token(token: str | None) -> bool:
    return _matches_any(token, _legacy_token_values("app"))


def is_legacy_upload_token(token: str | None) -> bool:
    return _matches_any(token, _legacy_token_values("upload"))


def _matches_any(token: str | None, values: set[str]) -> bool:
    if not token:
        return False
    return any(compare_digest(token, value) for value in values if value)


def _legacy_ledgers_from_config() -> list[Tenant]:
    tenants = list(configured_tenants())
    return tenants or [Tenant(id=DEFAULT_TENANT_ID, name=DEFAULT_TENANT_NAME, upload_token="", app_token="")]


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


def _ensure_device(db: Session, account_id: int, device_name: str, platform: str) -> Device:
    device = Device(
        account_id=account_id,
        device_name=_clean_name(device_name, "未命名设备"),
        platform=_clean_name(platform, "unknown").lower()[:32],
    )
    db.add(device)
    db.flush()
    return device


def _create_auth_token(db: Session, *, account_id: int, device_id: int, ledger_id: str, scope: str) -> str:
    return issue_auth_token(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        scope=scope,
    )


def _create_upload_link(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    ledger_id: str,
    default_timezone: str | None,
) -> str:
    return issue_upload_link(
        db,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        default_timezone=default_timezone,
    )


def _create_pairing_code(
    db: Session,
    *,
    ledger_id: str,
    account_id: int | None,
    device_name_hint: str | None = None,
    ttl_minutes: int = PAIRING_CODE_TTL_MINUTES,
) -> PairingCodeResult:
    ledger = _ledger_by_id(db, ledger_id)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invalid_request", status_code=422)
    ttl = max(1, min(ttl_minutes, 60))
    expires_at = now_utc() + timedelta(minutes=ttl)
    while True:
        code = new_pairing_code()
        code_hash = hash_pairing_code(code)
        if db.scalar(select(PairingCode.id).where(PairingCode.code_hash == code_hash).limit(1)) is None:
            break
    pairing = PairingCode(
        code_hash=code_hash,
        ledger_id=ledger.ledger_id,
        account_id=account_id,
        device_name_hint=_clean_name(device_name_hint, "") or None,
        expires_at=expires_at,
    )
    db.add(pairing)
    db.flush()
    return PairingCodeResult(pairing_code=code, ledger_name=ledger.name, expires_at=to_iso(expires_at) or "")


def create_pairing_code(
    db: Session,
    *,
    ledger_id: str,
    account_id: int | None,
    device_name_hint: str | None = None,
    ttl_minutes: int = PAIRING_CODE_TTL_MINUTES,
) -> PairingCodeResult:
    result = _create_pairing_code(
        db,
        ledger_id=ledger_id,
        account_id=account_id,
        device_name_hint=device_name_hint,
        ttl_minutes=ttl_minutes,
    )
    db.commit()
    return result


def bootstrap_owner(
    db: Session,
    *,
    account_name: str | None = None,
    ledger_name: str | None = None,
    device_name: str | None = None,
    default_timezone: str | None = None,
    commit: bool = True,
) -> BootstrapResult:
    if active_auth_token_count(db) > 0:
        raise AppError("bootstrap_already_initialized", status_code=409)

    owner = _owner_account(db, _clean_name(account_name, DEFAULT_ACCOUNT_NAME))
    if account_name and owner.display_name == DEFAULT_ACCOUNT_NAME:
        owner.display_name = _clean_name(account_name, DEFAULT_ACCOUNT_NAME)
    default_ledger = _ensure_ledger(
        db,
        ledger_id=DEFAULT_TENANT_ID,
        name=_clean_name(ledger_name, DEFAULT_TENANT_NAME),
        owner_account=owner,
    )
    bootstrap_device = _ensure_device(
        db,
        owner.id,
        _clean_name(device_name, DEFAULT_BOOTSTRAP_DEVICE_NAME),
        "windows",
    )
    admin_token = _create_auth_token(
        db,
        account_id=owner.id,
        device_id=bootstrap_device.id,
        ledger_id=default_ledger.ledger_id,
        scope="admin",
    )
    upload_key = _create_upload_link(
        db,
        account_id=owner.id,
        device_id=bootstrap_device.id,
        ledger_id=default_ledger.ledger_id,
        default_timezone=default_timezone or get_settings().ocr_default_timezone,
    )
    pairing = _create_pairing_code(
        db,
        ledger_id=default_ledger.ledger_id,
        account_id=owner.id,
        device_name_hint="Android",
    )
    if commit:
        db.commit()
    return BootstrapResult(
        account_name=owner.display_name,
        ledger_id=default_ledger.ledger_id,
        ledger_name=default_ledger.name,
        device_name=bootstrap_device.device_name,
        admin_token=admin_token,
        upload_key=upload_key,
        upload_url_path=f"/u/{upload_key}",
        pairing_code=pairing.pairing_code,
        pairing_expires_at=pairing.expires_at,
    )


def _role_for(db: Session, ledger_id: str, account_id: int) -> str:
    member = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )
    if member is None:
        raise AppError("invalid_token", status_code=401)
    return member.role


def _context_from_token(db: Session, token: AuthToken) -> AuthContext:
    account = db.get(Account, token.account_id)
    device = db.get(Device, token.device_id)
    ledger = _ledger_by_id(db, token.ledger_id)
    if account is None or account.disabled_at is not None or device is None or device.revoked_at is not None:
        raise AppError("invalid_token", status_code=401)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invalid_token", status_code=401)
    role = _role_for(db, ledger.ledger_id, account.id)
    now = now_utc()
    token.last_used_at = now
    device.last_seen_at = now
    db.commit()
    return AuthContext(
        account_id=account.id,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_id=device.id,
        device_name=device.device_name,
        role=role,
        scope=token.scope,
    )


def authenticate_session_token(db: Session, token_value: str, allowed_scopes: set[str]) -> AuthContext:
    token_hash = hash_secret(token_value)
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == token_hash)
        .where(AuthToken.revoked_at.is_(None))
        .limit(1)
    )
    if token is None or token.scope not in allowed_scopes:
        raise AppError("invalid_token", status_code=401)
    return _context_from_token(db, token)


def authenticate_upload_link(db: Session, upload_key: str) -> AuthContext:
    link = db.scalar(
        select(UploadLink)
        .where(UploadLink.token_hash == hash_secret(upload_key))
        .where(UploadLink.revoked_at.is_(None))
        .limit(1)
    )
    if link is None:
        raise AppError("invalid_token", status_code=401)
    account = db.get(Account, link.account_id)
    device = db.get(Device, link.device_id)
    ledger = _ledger_by_id(db, link.ledger_id)
    if account is None or account.disabled_at is not None or device is None or device.revoked_at is not None:
        raise AppError("invalid_token", status_code=401)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invalid_token", status_code=401)
    role = _role_for(db, ledger.ledger_id, account.id)
    now = now_utc()
    link.last_used_at = now
    device.last_seen_at = now
    db.commit()
    return AuthContext(
        account_id=account.id,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_id=device.id,
        device_name=device.device_name,
        role=role,
        scope="upload",
    )


def upload_link_default_timezone(db: Session, upload_key: str) -> str | None:
    link = db.scalar(
        select(UploadLink)
        .where(UploadLink.token_hash == hash_secret(upload_key))
        .where(UploadLink.revoked_at.is_(None))
        .limit(1)
    )
    return link.default_timezone if link is not None else None


def pair_device(
    db: Session,
    *,
    pairing_code: str,
    device_name: str,
    platform: str,
    remote_id: str | None = None,
) -> PairingResult:
    _check_pairing_attempt_limit(remote_id)
    code_hash = hash_pairing_code(pairing_code.strip())
    pairing = db.scalar(select(PairingCode).where(PairingCode.code_hash == code_hash).limit(1))
    if pairing is None:
        _reject_pairing(remote_id, "invalid_pairing_code", 401)
    if pairing.used_at is not None:
        _reject_pairing(remote_id, "pairing_code_used", 409)
    if (ensure_utc(pairing.expires_at) or pairing.expires_at) <= now_utc():
        _reject_pairing(remote_id, "pairing_code_expired", 410)

    ledger = _ledger_by_id(db, pairing.ledger_id)
    if ledger is None or ledger.archived_at is not None:
        _reject_pairing(remote_id, "invalid_pairing_code", 401)
    account_id = pairing.account_id or ledger.owner_account_id
    account = db.get(Account, account_id)
    if account is None or account.disabled_at is not None:
        _reject_pairing(remote_id, "invalid_pairing_code", 401)
    role = _role_for(db, ledger.ledger_id, account.id)

    used_at = now_utc()
    consume_result = consume_pairing_code(db, pairing_id=pairing.id, used_at=used_at)
    if consume_result != "consumed":
        db.rollback()
        if consume_result == "used":
            _reject_pairing(remote_id, "pairing_code_used", 409)
        _reject_pairing(remote_id, "pairing_code_expired", 410)

    device = _ensure_device(db, account.id, device_name, platform)
    token = _create_auth_token(
        db,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        scope="app",
    )
    db.commit()
    _clear_pairing_failures(remote_id)
    return PairingResult(
        session_token=token,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=role,
    )
