from __future__ import annotations

import base64
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_UPLOAD_TOKEN = "pytest-upload-token"
TEST_APP_TOKEN = "pytest-app-token"
TEST_ADMIN_TOKEN = "pytest-admin-token"
TEST_TENANT_UPLOAD_TOKEN = "pytest-tenant-upload-token"
TEST_TENANT_APP_TOKEN = "pytest-tenant-app-token"
TEST_DB_PATH = BACKEND_ROOT / "data" / "pytest_test.db"
TEST_UPLOAD_DIR = BACKEND_ROOT / "uploads" / "pytest_test"

os.environ.update(
    {
        "UPLOAD_TOKEN": TEST_UPLOAD_TOKEN,
        "APP_TOKEN": TEST_APP_TOKEN,
        "ADMIN_TOKEN": TEST_ADMIN_TOKEN,
        "DATABASE_URL": "sqlite:///data/pytest_test.db",
        "UPLOAD_DIR": "uploads/pytest_test",
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

from app.database import Base, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def app_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_APP_TOKEN}"}


def upload_headers() -> dict[str, str]:
    return {"Upload-Token": TEST_UPLOAD_TOKEN}


def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}


def gray_app_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TENANT_APP_TOKEN}"}


def gray_upload_headers() -> dict[str, str]:
    return {"Upload-Token": TEST_TENANT_UPLOAD_TOKEN}


def reset_runtime() -> None:
    Base.metadata.drop_all(bind=engine)
    shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
    init_db()


@pytest.fixture()
def client() -> TestClient:
    reset_runtime()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_runtime()
