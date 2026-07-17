from __future__ import annotations

import json
import sys
from pathlib import Path


def verify_report(report_path: Path) -> tuple[int, int]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("OWASP aggregate report contains no scanned dependencies")
    app_references = {
        reference
        for dependency in dependencies
        if isinstance(dependency, dict)
        for reference in dependency.get("projectReferences", [])
        if isinstance(reference, str) and reference.startswith("app:")
    }
    if not app_references:
        raise ValueError("OWASP aggregate report contains no :app project reference")
    return len(dependencies), len(app_references)


def main() -> int:
    if len(sys.argv) != 2:
        raise ValueError("expected one dependency-check JSON report path")
    dependencies, app_references = verify_report(Path(sys.argv[1]))
    print(
        "OWASP_APP_REPORT_VERIFIED "
        f"dependencies={dependencies} app_references={app_references}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
