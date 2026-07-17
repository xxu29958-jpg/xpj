from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dependency_check_contract import (
    EXPECTED_APP_REFERENCES,
    MAX_FUTURE_SKEW_SECONDS,
    PAYLOAD_TTL_SECONDS,
    SHA256_PATTERN,
    assert_secret_absent,
    dependency_check_version,
    load_json,
    parse_timestamp,
    require_mapping,
    require_nonempty_string,
    version_catalog_path,
)

_REPORT_SCHEMA = "1.1"


@dataclass(frozen=True)
class ReportIdentity:
    dependency_count: int
    app_reference_count: int
    nvd_checked_epoch: int


def _validate_app_dependency(dependency: dict[str, Any]) -> None:
    is_virtual = dependency.get("isVirtual")
    if not isinstance(is_virtual, bool):
        raise ValueError("app dependency isVirtual must be a boolean")
    file_name = require_nonempty_string(
        dependency.get("fileName"),
        label="app dependency fileName",
    )
    require_nonempty_string(
        dependency.get("filePath"),
        label="app dependency filePath",
    )
    evidence = require_mapping(
        dependency.get("evidenceCollected"),
        label="app dependency evidenceCollected",
    )
    for key in ("vendorEvidence", "productEvidence", "versionEvidence"):
        if not isinstance(evidence.get(key), list):
            raise ValueError(f"app dependency {key} must be an array")
    if is_virtual:
        if ":" not in file_name or any(
            character.isspace() for character in file_name
        ):
            raise ValueError("virtual app dependency has no coordinate-like identity")
    else:
        sha256 = dependency.get("sha256")
        if (
            not isinstance(sha256, str)
            or SHA256_PATTERN.fullmatch(sha256.lower()) is None
        ):
            raise ValueError("non-virtual app dependency has no SHA-256 identity")


def _nvd_checked_epoch(data_sources: object) -> int:
    if not isinstance(data_sources, list) or not data_sources:
        raise ValueError("OWASP aggregate report contains no data-source metadata")
    nvd_checked_timestamps = []
    for source in data_sources:
        source_document = require_mapping(source, label="report data source")
        source_name = require_nonempty_string(
            source_document.get("name"),
            label="report data-source name",
        )
        source_timestamp = source_document.get("timestamp")
        require_nonempty_string(
            source_timestamp,
            label="report data-source timestamp",
        )
        if source_name == "NVD API Last Checked":
            nvd_checked_timestamps.append(
                parse_timestamp(
                    source_timestamp,
                    label="NVD API Last Checked timestamp",
                )
            )
    if len(nvd_checked_timestamps) != 1:
        raise ValueError(
            "OWASP aggregate report must contain one NVD API Last Checked timestamp"
        )
    checked_epoch = int(nvd_checked_timestamps[0].timestamp())
    now_epoch = int(time.time())
    if checked_epoch > now_epoch + MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("OWASP report NVD check time is in the future")
    if checked_epoch + PAYLOAD_TTL_SECONDS <= now_epoch:
        raise ValueError("OWASP report NVD metadata has expired")
    return checked_epoch


def _app_references(dependencies: list[object]) -> set[str]:
    app_references: set[str] = set()
    for raw_dependency in dependencies:
        dependency = require_mapping(
            raw_dependency,
            label="report dependency",
        )
        references = dependency.get("projectReferences", [])
        if not isinstance(references, list) or not all(
            isinstance(reference, str) and bool(reference)
            for reference in references
        ):
            raise ValueError("dependency projectReferences must be an array of strings")
        matched_references = EXPECTED_APP_REFERENCES.intersection(references)
        if not matched_references:
            continue
        _validate_app_dependency(dependency)
        app_references.update(matched_references)
    missing_references = EXPECTED_APP_REFERENCES - app_references
    if missing_references:
        missing = ", ".join(sorted(missing_references))
        raise ValueError(
            "OWASP aggregate report is missing required :app runtime scope: "
            f"{missing}"
        )
    return app_references


def verify_report(
    report_path: Path,
    *,
    catalog_path: Path,
) -> ReportIdentity:
    report = load_json(report_path, label="OWASP aggregate report")
    if report.get("reportSchema") != _REPORT_SCHEMA:
        raise ValueError("OWASP aggregate report schema is unsupported")

    scan_info = require_mapping(
        report.get("scanInfo"),
        label="report scanInfo",
    )
    expected_version = dependency_check_version(catalog_path)
    if scan_info.get("engineVersion") != expected_version:
        raise ValueError("OWASP report engine version does not match this checkout")
    checked_epoch = _nvd_checked_epoch(scan_info.get("dataSource"))
    if "analysisExceptions" in scan_info:
        exceptions = scan_info["analysisExceptions"]
        if not isinstance(exceptions, list) or exceptions:
            raise ValueError("OWASP aggregate report contains analysis exceptions")

    project_info = require_mapping(
        report.get("projectInfo"),
        label="report projectInfo",
    )
    require_nonempty_string(
        project_info.get("name"),
        label="report projectInfo.name",
    )
    parse_timestamp(
        project_info.get("reportDate"),
        label="report projectInfo.reportDate",
    )

    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("OWASP aggregate report contains no scanned dependencies")
    app_references = _app_references(dependencies)
    return ReportIdentity(
        dependency_count=len(dependencies),
        app_reference_count=len(app_references),
        nvd_checked_epoch=checked_epoch,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--version-catalog", type=Path)
    args = parser.parse_args()

    assert_secret_absent()
    report_identity = verify_report(
        args.report,
        catalog_path=args.version_catalog or version_catalog_path(),
    )
    print(
        "OWASP_APP_REPORT_VERIFIED "
        f"dependencies={report_identity.dependency_count} "
        f"app_references={report_identity.app_reference_count} "
        f"nvd_checked_epoch={report_identity.nvd_checked_epoch}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
