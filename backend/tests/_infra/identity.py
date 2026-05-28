"""TestIdentity: owner + per-tenant secrets for a freshly-seeded test DB.

``seed_identity()`` bootstraps the owner account, creates one device per
tenant (``owner`` and ``tester_1``), and returns the secrets the test
suite needs to talk to the API. The returned ``TestIdentity`` is the
single source of truth — no module-level mutable globals.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Ledger, UploadLink
from app.services.identity_service import (
    bootstrap_owner,
    hash_secret,
    new_session_token,
    new_upload_key,
)
from app.services.session_lifecycle_service import upload_link_expires_at
from app.services.time_service import now_utc


@dataclass(frozen=True)
class TestIdentity:
    app_token: str
    admin_token: str
    upload_key: str
    pairing_code: str
    tenant_app_token: str
    tenant_upload_key: str

    @property
    def app_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.app_token}"}

    @property
    def admin_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.admin_token}"}

    @property
    def upload_headers(self) -> dict[str, str]:
        return {}

    @property
    def gray_app_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tenant_app_token}"}

    @property
    def gray_upload_headers(self) -> dict[str, str]:
        return {}

    @property
    def upload_url_path(self) -> str:
        return f"/u/{self.upload_key}"

    @property
    def gray_upload_url_path(self) -> str:
        return f"/u/{self.tenant_upload_key}"


def seed_identity() -> TestIdentity:
    """Bootstrap owner + per-tenant devices/tokens. DB must already be fresh."""
    with SessionLocal() as db:
        bootstrap = bootstrap_owner(
            db, account_name="我", ledger_name="我的小票夹", device_name="pytest-owner"
        )
        admin_token = bootstrap.admin_token
        upload_key = bootstrap.upload_key
        pairing_code = bootstrap.pairing_code

    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        owner_ledger = db.query(Ledger).filter(Ledger.ledger_id == "owner").one()
        tester_ledger = db.query(Ledger).filter(Ledger.ledger_id == "tester_1").one()

        owner_device = Device(account_id=owner.id, device_name="pytest-android", platform="android")
        tester_device = Device(account_id=owner.id, device_name="pytest-gray-android", platform="android")
        db.add_all([owner_device, tester_device])
        db.flush()

        app_token = new_session_token()
        tenant_app_token = new_session_token()
        tenant_upload_key = new_upload_key()
        issued_at = now_utc()
        db.add_all(
            [
                AuthToken(
                    token_hash=hash_secret(app_token),
                    account_id=owner.id,
                    device_id=owner_device.id,
                    ledger_id=owner_ledger.ledger_id,
                    scope="app",
                ),
                AuthToken(
                    token_hash=hash_secret(tenant_app_token),
                    account_id=owner.id,
                    device_id=tester_device.id,
                    ledger_id=tester_ledger.ledger_id,
                    scope="app",
                ),
                UploadLink(
                    token_hash=hash_secret(tenant_upload_key),
                    account_id=owner.id,
                    device_id=tester_device.id,
                    ledger_id=tester_ledger.ledger_id,
                    default_timezone="Asia/Shanghai",
                    expires_at=upload_link_expires_at(issued_at),
                ),
            ]
        )
        db.commit()

    return TestIdentity(
        app_token=app_token,
        admin_token=admin_token,
        upload_key=upload_key,
        pairing_code=pairing_code,
        tenant_app_token=tenant_app_token,
        tenant_upload_key=tenant_upload_key,
    )
