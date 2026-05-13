from __future__ import annotations

import base64
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_RUN_ID = f"pid_{os.getpid()}"
TEST_UPLOAD_TOKEN = "pytest-upload-token"
TEST_APP_TOKEN = "pytest-app-token"
TEST_ADMIN_TOKEN = "pytest-admin-token"
TEST_TENANT_UPLOAD_TOKEN = "pytest-tenant-upload-token"
TEST_TENANT_APP_TOKEN = "pytest-tenant-app-token"
TEST_DB_PATH = BACKEND_ROOT / "data" / f"pytest_test_{TEST_RUN_ID}.db"
TEST_UPLOAD_DIR = BACKEND_ROOT / "uploads" / f"pytest_test_{TEST_RUN_ID}"
TEST_UPLOAD_RELATIVE = TEST_UPLOAD_DIR.relative_to(BACKEND_ROOT).as_posix()
CURRENT_APP_TOKEN = ""
CURRENT_ADMIN_TOKEN = ""
CURRENT_UPLOAD_KEY = ""
CURRENT_PAIRING_CODE = ""
CURRENT_TENANT_APP_TOKEN = ""
CURRENT_TENANT_UPLOAD_KEY = ""

os.environ.update(
    {
        "UPLOAD_TOKEN": TEST_UPLOAD_TOKEN,
        "APP_TOKEN": TEST_APP_TOKEN,
        "ADMIN_TOKEN": TEST_ADMIN_TOKEN,
        "DATABASE_URL": f"sqlite:///data/{TEST_DB_PATH.name}",
        "UPLOAD_DIR": TEST_UPLOAD_RELATIVE,
        "MAX_UPLOAD_SIZE_MB": "10",
        "DELETE_IMAGE_AFTER_CONFIRM": "false",
        "GENERATE_THUMBNAIL": "true",
        "DELETE_IMAGE_AFTER_DAYS": "0",
        "OCR_PROVIDER": "empty",
        "TENANTS_JSON": json.dumps(
            [
                {
                    "id": "owner",
                    "name": "我的小票夹",
                    "upload_token": TEST_UPLOAD_TOKEN,
                    "app_token": TEST_APP_TOKEN,
                },
                {
                    "id": "tester_1",
                    "name": "灰度用户1",
                    "upload_token": TEST_TENANT_UPLOAD_TOKEN,
                    "app_token": TEST_TENANT_APP_TOKEN,
                },
            ],
            ensure_ascii=False,
        ),
    },
)

from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, AuthToken, Device, Ledger, UploadLink  # noqa: E402
from app.services.identity_service import bootstrap_owner, hash_secret, new_session_token, new_upload_key  # noqa: E402


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)


def app_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {CURRENT_APP_TOKEN}"}


def upload_headers() -> dict[str, str]:
    return {}


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {CURRENT_ADMIN_TOKEN}"}


def gray_app_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {CURRENT_TENANT_APP_TOKEN}"}


def gray_upload_headers() -> dict[str, str]:
    return {}


def upload_url_path() -> str:
    return f"/u/{CURRENT_UPLOAD_KEY}"


def gray_upload_url_path() -> str:
    return f"/u/{CURRENT_TENANT_UPLOAD_KEY}"


def _seed_test_identity_tokens() -> None:
    global CURRENT_APP_TOKEN
    global CURRENT_ADMIN_TOKEN
    global CURRENT_UPLOAD_KEY
    global CURRENT_PAIRING_CODE
    global CURRENT_TENANT_APP_TOKEN
    global CURRENT_TENANT_UPLOAD_KEY

    with SessionLocal() as db:
        bootstrap = bootstrap_owner(db, account_name="我", ledger_name="我的小票夹", device_name="pytest-owner")
        CURRENT_ADMIN_TOKEN = bootstrap.admin_token
        CURRENT_UPLOAD_KEY = bootstrap.upload_key
        CURRENT_PAIRING_CODE = bootstrap.pairing_code

    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        owner_ledger = db.query(Ledger).filter(Ledger.ledger_id == "owner").one()
        tester_ledger = db.query(Ledger).filter(Ledger.ledger_id == "tester_1").one()

        owner_device = Device(account_id=owner.id, device_name="pytest-android", platform="android")
        tester_device = Device(account_id=owner.id, device_name="pytest-gray-android", platform="android")
        db.add_all([owner_device, tester_device])
        db.flush()

        CURRENT_APP_TOKEN = new_session_token()
        CURRENT_TENANT_APP_TOKEN = new_session_token()
        CURRENT_TENANT_UPLOAD_KEY = new_upload_key()
        db.add_all(
            [
                AuthToken(
                    token_hash=hash_secret(CURRENT_APP_TOKEN),
                    account_id=owner.id,
                    device_id=owner_device.id,
                    ledger_id=owner_ledger.ledger_id,
                    scope="app",
                ),
                AuthToken(
                    token_hash=hash_secret(CURRENT_TENANT_APP_TOKEN),
                    account_id=owner.id,
                    device_id=tester_device.id,
                    ledger_id=tester_ledger.ledger_id,
                    scope="app",
                ),
                UploadLink(
                    token_hash=hash_secret(CURRENT_TENANT_UPLOAD_KEY),
                    account_id=owner.id,
                    device_id=tester_device.id,
                    ledger_id=tester_ledger.ledger_id,
                    default_timezone="Asia/Shanghai",
                ),
            ]
        )
        db.commit()


def reset_runtime() -> None:
    Base.metadata.drop_all(bind=engine)
    shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
    init_db()
    _seed_test_identity_tokens()


def _cleanup_test_runtime() -> None:
    engine.dispose()
    shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = TEST_DB_PATH.with_name(f"{TEST_DB_PATH.name}{suffix}")
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _cleanup_test_runtime()


@pytest.fixture()
def client() -> TestClient:
    reset_runtime()
    # v0.3-rc1-preflight: bypass the public-host network boundary for the
    # default TestClient (peer=testclient, host=testserver). Boundary
    # behaviour is exercised directly in tests/test_owner_console.py via
    # the network_boundary helper.
    from app.network_boundary import require_admin_network_boundary
    app.dependency_overrides[require_admin_network_boundary] = lambda: None
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()
