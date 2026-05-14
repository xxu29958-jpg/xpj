from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.migration_readiness_service import build_v1_migration_readiness_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v1.0 migration readiness checks.")
    parser.add_argument(
        "--create-backup",
        action="store_true",
        help="Create a named pre-v1.0 SQLite backup before reporting readiness.",
    )
    args = parser.parse_args()

    report = build_v1_migration_readiness_report(create_backup=args.create_backup)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ready else 1


if __name__ == "__main__":
    sys.exit(main())
