"""Test environment wiring.

Importing this module sets ``os.environ`` to the test-suite values **before**
any ``app.*`` module is loaded, so ``app.config.get_settings()`` reads the
right database URL / upload paths / tokens.

Keep this module free of ``app.*`` imports — it runs at process start, before
the test DB even exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_RUN_ID = f"pid_{os.getpid()}"
TEST_UPLOAD_TOKEN = "pytest-upload-token"
TEST_APP_TOKEN = "pytest-app-token"
TEST_ADMIN_TOKEN = "pytest-admin-token"
TEST_TENANT_UPLOAD_TOKEN = "pytest-tenant-upload-token"
TEST_TENANT_APP_TOKEN = "pytest-tenant-app-token"
TEST_DB_PATH = BACKEND_ROOT / "data" / f"pytest_test_{TEST_RUN_ID}.db"
TEST_UPLOAD_DIR = BACKEND_ROOT / "uploads" / f"pytest_test_{TEST_RUN_ID}"
TEST_UPLOAD_RELATIVE = TEST_UPLOAD_DIR.relative_to(BACKEND_ROOT).as_posix()


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
