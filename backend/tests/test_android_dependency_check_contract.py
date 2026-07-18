from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests._infra.android_dependency_check import (
    assert_dependency_check_ci_contract,
    assert_runtime_dependency_suppressions,
)
from tests._infra.android_gradle_cache import (
    assert_codeql_android_build_contract,
    assert_github_gradle_cache_topology,
)
from tests._infra.ci_gap import load_ci_gap_audit as _load

pytestmark = pytest.mark.parallel_safe

_ROOT = Path(__file__).resolve().parents[2]
_REFERENCES = (
    "app:grayDebugRuntimeClasspath",
    "app:grayReleaseRuntimeClasspath",
    "app:internalDebugRuntimeClasspath",
    "app:internalReleaseRuntimeClasspath",
)
_ARTIFACT = {
    "group": "androidx.core",
    "name": "core-ktx",
    "version": "1.16.0",
    "fileName": "core-ktx-1.16.0.jar",
    "sha256": "a" * 64,
}
_PURL = "pkg:maven/androidx.core/core-ktx@1.16.0"


def _load_workflow(path: Path) -> dict:
    _load()
    parser = importlib.import_module("ci_gap_workflow_parser")
    return parser._load_workflow(path)


def _workflows() -> dict[str, dict]:
    return {
        path.name: _load_workflow(path)
        for path in (_ROOT / ".github" / "workflows").iterdir()
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    }


def test_android_dependency_scan_is_fail_closed_with_one_cache_writer() -> None:
    workflows = _workflows()
    android = workflows["ci.yml"]["jobs"]["android"]
    assert_dependency_check_ci_contract(android)
    assert_github_gradle_cache_topology(workflows)
    serialized = json.dumps(android, sort_keys=True)
    for forbidden in (
        "steps.owasp.outcome",
        "OWASP_NVD_UPDATE_TIMED_OUT",
        "OWASP_ANALYZE_TIMED_OUT",
        "NoDataException",
        "No documents exist",
    ):
        assert forbidden not in serialized

    gitea = _load_workflow(_ROOT / ".gitea" / "workflows" / "windows-ci.yml")
    assert gitea["jobs"]["android-unit"]["env"]["GRADLE_OPTS"] == (
        "-Dorg.gradle.caching=false"
    )


def test_prepare_android_keeps_runner_tuning_out_of_source_authority() -> None:
    action = _load_workflow(
        _ROOT / ".github" / "actions" / "prepare-android" / "action.yml"
    )
    steps = {step["name"]: step for step in action["runs"]["steps"]}
    tune = steps["Tune Gradle for cloud runner"]
    assert "set -euo pipefail" in tune["run"]
    assert 'runner_gradle_home="${GRADLE_USER_HOME:-$HOME/.gradle}"' in tune["run"]
    assert '>> "$runner_gradle_home/gradle.properties"' in tune["run"]
    assert ">> gradle.properties" not in tune["run"]

    codeql = _load_workflow(_ROOT / ".github" / "workflows" / "codeql.yml")
    assert_codeql_android_build_contract(codeql["jobs"]["analyze-android"])


def test_dependency_scan_report_verification_cannot_be_noop() -> None:
    android = _load_workflow(_ROOT / ".github" / "workflows" / "ci.yml")["jobs"][
        "android"
    ]
    verification = next(
        step
        for step in android["steps"]
        if step["name"] == "Verify Android dependency-check report"
    )
    verification["run"] = "exit 0"
    with pytest.raises(AssertionError):
        assert_dependency_check_ci_contract(android)


def test_gradle_cache_topology_rejects_a_second_writer() -> None:
    workflows = _workflows()
    connected = workflows["android-connected-test.yml"]
    setup_gradle = next(
        step
        for step in connected["jobs"]["connected"]["steps"]
        if step["name"] == "Set up Gradle"
    )
    setup_gradle["with"]["cache-read-only"] = False
    with pytest.raises(AssertionError):
        assert_github_gradle_cache_topology(workflows)


def test_suppression_contract_rejects_an_extra_broad_cpe(
    tmp_path: Path,
) -> None:
    source = (
        _ROOT
        / "android"
        / "config"
        / "dependency-check"
        / "suppressions.xml"
    )
    mutated = tmp_path / "suppressions.xml"
    shutil.copyfile(source, mutated)
    tree = ElementTree.parse(mutated)
    root = tree.getroot()
    namespace = root.tag.removesuffix("suppressions")
    first_rule = root.find(f"{namespace}suppress")
    assert first_rule is not None
    ElementTree.SubElement(first_rule, f"{namespace}cpe").text = (
        "cpe:/a:sqlite:sqlite"
    )
    tree.write(mutated, encoding="utf-8", xml_declaration=True)
    with pytest.raises(AssertionError):
        assert_runtime_dependency_suppressions(mutated)


def test_dependency_check_policy_is_fixed_to_shipped_runtime_scope() -> None:
    build = (_ROOT / "android" / "build.gradle.kts").read_text(encoding="utf-8")
    for fragment in (
        "failBuildOnCVSS = 7.0f",
        "failOnError = true",
        'scanProjects = listOf(":app")',
        '"grayDebugRuntimeClasspath"',
        '"grayReleaseRuntimeClasspath"',
        '"internalDebugRuntimeClasspath"',
        '"internalReleaseRuntimeClasspath"',
        "scanConfigurations = dependencyCheckRuntimeConfigurations",
        "analyzers.ossIndex.enabled = false",
        "hostedSuppressions.enabled = false",
        'tasks.register("exportDependencyCheckRuntimeInventory")',
        "outputs.upToDateWhen { false }",
        "autoUpdate = dependencyCheckAutoUpdate.get()",
        "nvd.validForHours = 24",
        "dependencyCheck.scanConfigurations ==",
        "dependencyCheckRuntimeConfigurations",
        'tasks.register("verifyDependencyCheckContract")',
        'tasks.named("dependencyCheckUpdate")',
        'tasks.named("dependencyCheckAggregate")',
    ):
        assert fragment in build
    for forbidden in (
        'providers.gradleProperty("dependencyCheckFailBuildOnCvss")',
        'providers.gradleProperty("nvdApiKey")',
        'providers.environmentVariable("ORG_GRADLE_PROJECT_nvdApiKey")',
        "dependencyCheckValidateNvd",
    ):
        assert forbidden not in build
    assert_runtime_dependency_suppressions(
        _ROOT / "android" / "config" / "dependency-check" / "suppressions.xml"
    )


def _timestamp(moment: datetime) -> str:
    return (
        moment.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _valid_report() -> dict:
    now = datetime.now(UTC)
    return {
        "reportSchema": "1.1",
        "scanInfo": {
            "engineVersion": "12.1.0",
            "dataSource": [
                {
                    "name": "NVD API Last Checked",
                    "timestamp": _timestamp(now),
                }
            ],
        },
        "projectInfo": {
            "name": "root project 'Ticketbox'",
            "artifactID": "Ticketbox",
            "reportDate": _timestamp(now),
        },
        "dependencies": [
            {
                "isVirtual": False,
                "fileName": _ARTIFACT["fileName"],
                "filePath": f"/gradle-cache/{_ARTIFACT['fileName']}",
                "sha256": _ARTIFACT["sha256"],
                "packages": [{"id": _PURL}],
                "projectReferences": list(_REFERENCES),
                "evidenceCollected": {
                    "vendorEvidence": [],
                    "productEvidence": [],
                    "versionEvidence": [],
                },
            }
        ],
    }


def _write_report_inputs(tmp_path: Path, report: dict) -> tuple[Path, Path, Path]:
    report_path = tmp_path / "report.json"
    inventory_path = tmp_path / "inventory.json"
    catalog_path = tmp_path / "libs.versions.toml"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    inventory_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "project": "Ticketbox",
                "configurations": {
                    reference: [dict(_ARTIFACT)] for reference in _REFERENCES
                },
            }
        ),
        encoding="utf-8",
    )
    catalog_path.write_text(
        "[plugins]\n"
        'owasp-dependency-check = { id = "org.owasp.dependencycheck", '
        'version = "12.1.0" }\n',
        encoding="utf-8",
    )
    return report_path, inventory_path, catalog_path


def _verify_report(
    tmp_path: Path,
    report: dict,
    *,
    secret: str | None = None,
) -> subprocess.CompletedProcess[str]:
    report_path, inventory_path, catalog_path = _write_report_inputs(
        tmp_path, report
    )
    env = os.environ.copy()
    if secret is None:
        env.pop("NVD_API_KEY", None)
    else:
        env["NVD_API_KEY"] = secret
    return subprocess.run(
        [
            sys.executable,
            str(
                _ROOT
                / "android"
                / "scripts"
                / "verify_dependency_check_report.py"
            ),
            str(report_path),
            "--inventory",
            str(inventory_path),
            "--version-catalog",
            str(catalog_path),
        ],
        cwd=_ROOT / "android",
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_report_verifier_accepts_current_complete_runtime_evidence(
    tmp_path: Path,
) -> None:
    result = _verify_report(tmp_path, _valid_report())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OWASP_APP_REPORT_VERIFIED" in result.stdout


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-engine",
        "stale-nvd",
        "partial-scope",
        "analysis-exception",
        "wrong-package",
    ],
)
def test_report_verifier_rejects_incomplete_or_untrusted_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    report = _valid_report()
    if mutation == "wrong-engine":
        report["scanInfo"]["engineVersion"] = "99.0.0"
    elif mutation == "stale-nvd":
        report["scanInfo"]["dataSource"][0]["timestamp"] = _timestamp(
            datetime.now(UTC) - timedelta(hours=25)
        )
    elif mutation == "partial-scope":
        report["dependencies"][0]["projectReferences"] = [_REFERENCES[0]]
    elif mutation == "analysis-exception":
        report["scanInfo"]["analysisExceptions"] = [{"message": "failed"}]
    elif mutation == "wrong-package":
        report["dependencies"][0]["packages"] = [
            {"id": "pkg:maven/androidx.core/core@1.16.0"}
        ]
    result = _verify_report(tmp_path, report)
    assert result.returncode != 0
    assert "::error::" in result.stderr


def test_report_verifier_process_never_receives_the_nvd_secret(
    tmp_path: Path,
) -> None:
    result = _verify_report(tmp_path, _valid_report(), secret="not-for-verifier")
    assert result.returncode != 0
    assert "credential reached a read-only verification process" in result.stderr
