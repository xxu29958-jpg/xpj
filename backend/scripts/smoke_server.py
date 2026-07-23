"""Child-owned smoke server lifecycle and dedicated database lease."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import uvicorn

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import dedicated_test_database_lease

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _clean_upload_runtime() -> None:
    upload_dir = (BACKEND_ROOT / "uploads" / "smoke_test").resolve()
    upload_root = (BACKEND_ROOT / "uploads").resolve()
    upload_dir.relative_to(upload_root)
    for _ in range(20):
        if not upload_dir.exists():
            return
        try:
            shutil.rmtree(upload_dir)
            return
        except PermissionError:
            time.sleep(0.1)
    raise RuntimeError("smoke upload runtime could not be cleared")


def main() -> int:
    database_url = os.environ["DATABASE_URL"]
    cluster_identity = os.environ["XPJ_TEST_CLUSTER_IDENTITY"]
    passfile = os.environ.get("PGPASSFILE")
    host = os.environ["XPJ_SMOKE_HOST"]
    port = int(os.environ["XPJ_SMOKE_PORT"])
    with dedicated_test_database_lease(
        database_url,
        expected_database=TEST_POSTGRES_CONTRACT.smoke_database,
        reset=True,
        cluster_identity=cluster_identity,
        passfile=passfile,
    ):
        _clean_upload_runtime()
        try:
            uvicorn.run(
                "app.main:app",
                host=host,
                port=port,
                access_log=False,
            )
        finally:
            _clean_upload_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
