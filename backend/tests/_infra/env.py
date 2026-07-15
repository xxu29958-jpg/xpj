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

from scripts.test_pg_contract import configured_test_database_url
from tests._infra.worker_db import worker_database_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER")
TEST_RUN_UID = os.environ.get("PYTEST_XDIST_TESTRUNUID")
TEST_RUN_ID = f"{TEST_WORKER_ID or 'main'}_pid_{os.getpid()}"
TEST_UPLOAD_TOKEN = "pytest-upload-token"
TEST_APP_TOKEN = "pytest-app-token"
TEST_ADMIN_TOKEN = "pytest-admin-token"
TEST_TENANT_UPLOAD_TOKEN = "pytest-tenant-upload-token"
TEST_TENANT_APP_TOKEN = "pytest-tenant-app-token"
TEST_RUNTIME_ROOT = BACKEND_ROOT / ".pytest-runtime"
TEST_DATA_DIR = TEST_RUNTIME_ROOT / TEST_RUN_ID
TEST_UPLOAD_DIR = BACKEND_ROOT / "uploads" / f"pytest_test_{TEST_RUN_ID}"
TEST_UPLOAD_RELATIVE = TEST_UPLOAD_DIR.relative_to(BACKEND_ROOT).as_posix()


# Lane (PG-only — debt #4, building on ADR-0041). PostgreSQL is the only lane:
# prod / dev / test share the engine so dialect drift can't hide.
# - XPJ_TEST_DATABASE_URL set  -> that engine verbatim only when paired with
#   XPJ_TEST_CLUSTER_CONFIRMED=1 (CI's ephemeral PG or an explicit override).
# - default                    -> local throwaway PostgreSQL on :5438, brought up
#   by backend/scripts/start_test_pg.ps1.
_base_database_url = configured_test_database_url(os.environ)
TEST_DATABASE_URL = (
    worker_database_url(_base_database_url, TEST_WORKER_ID, TEST_RUN_UID or "")
    if TEST_WORKER_ID is not None
    else _base_database_url
)

os.environ.update(
    {
        "UPLOAD_TOKEN": TEST_UPLOAD_TOKEN,
        "APP_TOKEN": TEST_APP_TOKEN,
        "ADMIN_TOKEN": TEST_ADMIN_TOKEN,
        "DATABASE_URL": TEST_DATABASE_URL,
        "TICKETBOX_DATA_DIR": str(TEST_DATA_DIR),
        "UPLOAD_DIR": str(TEST_UPLOAD_DIR),
        "MAX_UPLOAD_SIZE_MB": "10",
        "DELETE_IMAGE_AFTER_CONFIRM": "false",
        "GENERATE_THUMBNAIL": "true",
        "DELETE_IMAGE_AFTER_DAYS": "0",
        "OCR_PROVIDER": "empty",
        # Batch 1 public surface hardening defaults disabled in tests
        # (default lane fires multiple uploads through the same upload
        # link in quick succession). Dedicated throttle / quota tests
        # opt back in via monkeypatch.
        "UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS": "0",
        "UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET": "0",
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
