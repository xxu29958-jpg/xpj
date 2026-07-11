"""Database fixtures shared by admin device and UploadLink boundary tests."""

from __future__ import annotations

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Ledger, LedgerMember, UploadLink
from app.services.identity_service import hash_secret
from app.services.session_lifecycle_service import upload_link_expires_at
from app.services.time_service import now_utc


def insert_external_device_and_upload_link() -> tuple[str, str]:
    now = now_utc()
    with SessionLocal() as db:
        account = Account(display_name="external admin boundary", created_at=now)
        db.add(account)
        db.flush()
        ledger = Ledger(
            ledger_id="external_admin_boundary",
            name="external admin boundary",
            owner_account_id=account.id,
            created_at=now,
        )
        db.add(ledger)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id=ledger.ledger_id,
                account_id=account.id,
                role="owner",
                created_at=now,
            )
        )
        device = Device(
            account_id=account.id,
            device_name="external phone",
            platform="android",
            created_at=now,
        )
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret("external-device-token"),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger.ledger_id,
                scope="app",
                created_at=now,
            )
        )
        link = UploadLink(
            token_hash=hash_secret("external-upload-token"),
            account_id=account.id,
            device_id=device.id,
            ledger_id=ledger.ledger_id,
            created_at=now,
            expires_at=upload_link_expires_at(now),
        )
        db.add(link)
        db.commit()
        return device.public_id, link.public_id
