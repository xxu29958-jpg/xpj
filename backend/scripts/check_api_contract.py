"""Read-only contract drift check.

Dumps the FastAPI app's OpenAPI schema, compares it against the snapshot
committed at ``docs/architecture/openapi_contract.json``. CI fails when
the live schema diverges — the developer must either intentionally
regenerate the snapshot (and bring Android DTOs along) or fix the
backend change.

This is the minimal version of S-010: it catches *any* backend schema
shift (added route, removed field, changed required-ness, type change)
before it reaches the Android client. The Android side still hand-rolls
DTOs; pairing this script with the existing
``android/app/src/test/.../ApiDtoContractTest.kt`` gives two-sided
coverage.

Usage:
  python scripts/check_api_contract.py            # check (CI)
  python scripts/check_api_contract.py --update   # regenerate snapshot
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SNAPSHOT_PATH = REPO_ROOT / "docs" / "architecture" / "openapi_contract.json"

# Make ``app.*`` importable when invoked from anywhere (CI runs from repo
# root, dev from backend/, etc.).
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_app_openapi() -> dict:
    """Import the FastAPI app and return its OpenAPI document.

    Environment is seeded with safe placeholder secrets so the import
    succeeds without a real config. This is the same trick the test
    suite uses (``tests/_infra/env.py``); we duplicate the minimal subset
    here so the script runs standalone in CI.
    """
    os.environ.setdefault("UPLOAD_TOKEN", "contract-upload-token")
    os.environ.setdefault("APP_TOKEN", "contract-app-token")
    os.environ.setdefault("ADMIN_TOKEN", "contract-admin-token")
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    os.environ.setdefault("UPLOAD_DIR", "uploads/_contract_tmp")
    os.environ.setdefault("MAX_UPLOAD_SIZE_MB", "10")
    os.environ.setdefault("OCR_PROVIDER", "empty")

    # Reset settings cache in case a previous import already snapshotted.
    from app.config import reset_settings_cache
    from app.tenants import reset_tenant_cache

    reset_settings_cache()
    reset_tenant_cache()

    from app.main import app

    return app.openapi()


def _normalise(doc: dict) -> str:
    """Stable JSON serialization for diffing — sorted keys, indented."""
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate the snapshot instead of checking against it. "
        "Use this when an API change is intentional.",
    )
    args = parser.parse_args(argv)

    live = _normalise(_load_app_openapi())

    if args.update:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(live + "\n", encoding="utf-8")
        print(f"snapshot updated: {SNAPSHOT_PATH}")
        return 0

    if not SNAPSHOT_PATH.is_file():
        print(
            f"ERROR: snapshot missing at {SNAPSHOT_PATH}\n"
            "Run `python scripts/check_api_contract.py --update` to create it.",
            file=sys.stderr,
        )
        return 2

    snapshot = SNAPSHOT_PATH.read_text(encoding="utf-8").rstrip("\n")
    if live == snapshot:
        print("OpenAPI contract: up to date.")
        return 0

    diff = "\n".join(
        difflib.unified_diff(
            snapshot.splitlines(),
            live.splitlines(),
            fromfile="snapshot",
            tofile="live",
            n=3,
        )
    )
    print("ERROR: OpenAPI schema has drifted from the committed snapshot.", file=sys.stderr)
    print(diff[:8000], file=sys.stderr)
    print(
        "\nIf the change is intentional, run "
        "`python scripts/check_api_contract.py --update` and ensure the "
        "Android DTOs are updated to match.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
