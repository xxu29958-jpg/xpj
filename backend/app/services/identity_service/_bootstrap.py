"""First-time owner bootstrap: account + ledger + device + token + upload + pairing."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.services.identity_service._device import (
    _create_auth_token,
    _create_pairing_code,
    _create_upload_link,
    _ensure_device,
)
from app.services.identity_service._models import (
    DEFAULT_ACCOUNT_NAME,
    DEFAULT_BOOTSTRAP_DEVICE_NAME,
    BootstrapResult,
)
from app.services.identity_service._seed import (
    _clean_name,
    _ensure_ledger,
    _owner_account,
    active_auth_token_count,
)
from app.tenants import DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME


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
