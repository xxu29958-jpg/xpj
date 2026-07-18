from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
    inventory_artifact_count: int
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


def _maven_purl(*, group: str, name: str, version: str) -> str:
    safe = "._~-"
    return (
        f"pkg:maven/{quote(group, safe=safe)}/{quote(name, safe=safe)}"
        f"@{quote(version, safe=safe)}"
    )


def _runtime_inventory(
    inventory_path: Path,
) -> tuple[str, dict[str, set[tuple[str, str]]], int]:
    inventory = load_json(inventory_path, label="runtime dependency inventory")
    if set(inventory) != {"schema", "project", "configurations"}:
        raise ValueError("runtime dependency inventory has unexpected fields")
    if inventory["schema"] != 1:
        raise ValueError("runtime dependency inventory schema is unsupported")
    project = require_nonempty_string(
        inventory["project"],
        label="runtime dependency inventory project",
    )
    configurations = require_mapping(
        inventory["configurations"],
        label="runtime dependency inventory configurations",
    )
    if set(configurations) != EXPECTED_APP_REFERENCES:
        raise ValueError("runtime dependency inventory configuration set is incomplete")

    identities: dict[str, set[tuple[str, str]]] = {}
    total = 0
    expected_fields = {"group", "name", "version", "fileName", "sha256"}
    for reference in sorted(EXPECTED_APP_REFERENCES):
        raw_artifacts = configurations[reference]
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise ValueError(f"runtime dependency inventory is empty for {reference}")
        reference_identities: set[tuple[str, str]] = set()
        full_identities: set[tuple[str, str, str]] = set()
        for raw_artifact in raw_artifacts:
            artifact = require_mapping(
                raw_artifact,
                label=f"runtime dependency inventory artifact for {reference}",
            )
            if set(artifact) != expected_fields:
                raise ValueError("runtime dependency inventory artifact fields drifted")
            group = require_nonempty_string(
                artifact["group"],
                label="runtime artifact group",
            )
            name = require_nonempty_string(
                artifact["name"],
                label="runtime artifact name",
            )
            version = require_nonempty_string(
                artifact["version"],
                label="runtime artifact version",
            )
            file_name = require_nonempty_string(
                artifact["fileName"],
                label="runtime artifact fileName",
            )
            digest = require_nonempty_string(
                artifact["sha256"],
                label="runtime artifact SHA-256",
            ).lower()
            if SHA256_PATTERN.fullmatch(digest) is None:
                raise ValueError("runtime artifact SHA-256 is invalid")
            purl = _maven_purl(group=group, name=name, version=version)
            if (purl, file_name, digest) in full_identities:
                raise ValueError("runtime dependency inventory contains a duplicate artifact")
            full_identities.add((purl, file_name, digest))
            reference_identities.add((purl, digest))
        identities[reference] = reference_identities
        total += len(full_identities)
    return project, identities, total


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


def _app_references(
    dependencies: list[object],
    *,
    inventory: dict[str, set[tuple[str, str]]],
) -> set[str]:
    app_references: set[str] = set()
    report_artifacts = {
        reference: set()
        for reference in EXPECTED_APP_REFERENCES
    }
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
        unknown_app_references = {
            reference
            for reference in references
            if reference.startswith("app:")
        } - EXPECTED_APP_REFERENCES
        if unknown_app_references:
            raise ValueError("OWASP report contains an unexpected :app reference")
        matched_references = EXPECTED_APP_REFERENCES.intersection(references)
        if not matched_references:
            continue
        _validate_app_dependency(dependency)
        packages = dependency.get("packages", [])
        if not isinstance(packages, list):
            raise ValueError("dependency packages must be an array")
        purls = set()
        for raw_package in packages:
            package = require_mapping(raw_package, label="report dependency package")
            package_id = require_nonempty_string(
                package.get("id"),
                label="report dependency package id",
            )
            if package_id.startswith("pkg:maven/"):
                purls.add(package_id)
        digest = dependency.get("sha256")
        normalized_digest = (
            digest.lower()
            if isinstance(digest, str)
            and SHA256_PATTERN.fullmatch(digest.lower()) is not None
            else None
        )
        if normalized_digest is not None:
            for reference in matched_references:
                report_artifacts[reference].update(
                    (purl, normalized_digest)
                    for purl in purls
                )
        app_references.update(matched_references)
    missing_references = EXPECTED_APP_REFERENCES - app_references
    if missing_references:
        missing = ", ".join(sorted(missing_references))
        raise ValueError(
            "OWASP aggregate report is missing required :app runtime scope: "
            f"{missing}"
        )
    for reference, expected_artifacts in inventory.items():
        missing_artifacts = expected_artifacts - report_artifacts[reference]
        if missing_artifacts:
            missing_purl, missing_digest = min(missing_artifacts)
            raise ValueError(
                "OWASP report does not cover resolved runtime artifact "
                f"{reference} {missing_purl} sha256={missing_digest}"
            )
    return app_references


def verify_report(
    report_path: Path,
    *,
    catalog_path: Path,
    inventory_path: Path,
) -> ReportIdentity:
    inventory_project, inventory, inventory_artifact_count = _runtime_inventory(
        inventory_path
    )
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
    report_artifact_id = require_nonempty_string(
        project_info.get("artifactID"),
        label="report projectInfo.artifactID",
    )
    if report_artifact_id != inventory_project:
        raise ValueError("OWASP report project does not match runtime inventory")
    parse_timestamp(
        project_info.get("reportDate"),
        label="report projectInfo.reportDate",
    )

    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("OWASP aggregate report contains no scanned dependencies")
    app_references = _app_references(dependencies, inventory=inventory)
    return ReportIdentity(
        dependency_count=len(dependencies),
        app_reference_count=len(app_references),
        inventory_artifact_count=inventory_artifact_count,
        nvd_checked_epoch=checked_epoch,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--version-catalog", type=Path)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("build/reports/dependency-check-runtime-inventory.json"),
    )
    args = parser.parse_args()

    assert_secret_absent()
    report_identity = verify_report(
        args.report,
        catalog_path=args.version_catalog or version_catalog_path(),
        inventory_path=args.inventory,
    )
    print(
        "OWASP_APP_REPORT_VERIFIED "
        f"dependencies={report_identity.dependency_count} "
        f"app_references={report_identity.app_reference_count} "
        f"inventory_artifacts={report_identity.inventory_artifact_count} "
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
