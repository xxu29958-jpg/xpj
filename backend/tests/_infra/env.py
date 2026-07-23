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

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.write_test_postgres_env import render_environment

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_UPLOAD_TOKEN = "pytest-upload-token"
TEST_APP_TOKEN = "pytest-app-token"
TEST_ADMIN_TOKEN = "pytest-admin-token"
TEST_TENANT_UPLOAD_TOKEN = "pytest-tenant-upload-token"
TEST_TENANT_APP_TOKEN = "pytest-tenant-app-token"
# Lane (PG-only — debt #4, building on ADR-0041). PostgreSQL is the only lane:
# prod / dev / test share the engine so dialect drift can't hide.
# - XPJ_TEST_DATABASE_URL set  -> that engine verbatim (CI's ephemeral PG, or any
#   explicit override).
# - default                    -> contract-defined local throwaway PostgreSQL,
#   brought up by backend/scripts/start_test_pg.ps1.
_explicit_database_url = os.environ.get("XPJ_TEST_DATABASE_URL")
_explicit_admin_url = os.environ.get("XPJ_TEST_ADMIN_URL")
if (_explicit_database_url is None) != (_explicit_admin_url is None):
    raise RuntimeError(
        "XPJ_TEST_DATABASE_URL and XPJ_TEST_ADMIN_URL must be supplied together"
    )
if _explicit_database_url is None:
    _local_postgres_environment = render_environment(
        host="localhost",
        port=TEST_POSTGRES_CONTRACT.ports.local,
        admin_user="postgres",
        application_user=TEST_POSTGRES_CONTRACT.application_role,
        passfile=TEST_POSTGRES_CONTRACT.default_data_dir(
            TEST_POSTGRES_CONTRACT.ports.local
        )
        / TEST_POSTGRES_CONTRACT.passfile_name,
        cluster_identity=TEST_POSTGRES_CONTRACT.local_database_identity(
            TEST_POSTGRES_CONTRACT.ports.local
        ),
    )
    BASE_TEST_DATABASE_URL = _local_postgres_environment["XPJ_TEST_DATABASE_URL"]
    ADMIN_TEST_DATABASE_URL = _local_postgres_environment["XPJ_TEST_ADMIN_URL"]
    os.environ.setdefault("PGPASSFILE", _local_postgres_environment["PGPASSFILE"])
    os.environ.setdefault(
        "XPJ_TEST_DATABASE_URL",
        _local_postgres_environment["XPJ_TEST_DATABASE_URL"],
    )
    os.environ.setdefault(
        "XPJ_TEST_CLUSTER_IDENTITY",
        _local_postgres_environment["XPJ_TEST_CLUSTER_IDENTITY"],
    )
    os.environ.setdefault(
        "XPJ_TEST_ADMIN_URL",
        _local_postgres_environment["XPJ_TEST_ADMIN_URL"],
    )
else:
    BASE_TEST_DATABASE_URL = _explicit_database_url
    ADMIN_TEST_DATABASE_URL = _explicit_admin_url
from tests._infra.worker_db import (  # noqa: E402
    sealed_test_database_url,
    worker_database_from_environment,
)

WORKER_DATABASE = worker_database_from_environment(
    BASE_TEST_DATABASE_URL,
    ADMIN_TEST_DATABASE_URL,
)
_database_url = (
    WORKER_DATABASE.database_url
    if WORKER_DATABASE
    else sealed_test_database_url(BASE_TEST_DATABASE_URL)
)
TEST_RUN_ID = (
    WORKER_DATABASE.runtime_id
    if WORKER_DATABASE
    else f"pid_{os.getpid()}"
)
TEST_UPLOAD_DIR = BACKEND_ROOT / "uploads" / f"pytest_test_{TEST_RUN_ID}"
TEST_UPLOAD_RELATIVE = TEST_UPLOAD_DIR.relative_to(BACKEND_ROOT).as_posix()
TEST_DATA_DIR = BACKEND_ROOT / "ticketbox-data" / "pytest" / TEST_RUN_ID

os.environ.update(
    {
        "UPLOAD_TOKEN": TEST_UPLOAD_TOKEN,
        "APP_TOKEN": TEST_APP_TOKEN,
        "ADMIN_TOKEN": TEST_ADMIN_TOKEN,
        "DATABASE_URL": _database_url,
        "TICKETBOX_DATA_DIR": str(TEST_DATA_DIR.resolve()),
        # Keep legacy relative DB references stable while the writable upload
        # directory itself is isolated per process/worker.
        "UPLOAD_DIR": str(TEST_UPLOAD_DIR.resolve()),
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
