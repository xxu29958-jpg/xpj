from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_gap_audit as _load

pytestmark = pytest.mark.parallel_safe

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_ACTION_SHA = "0057852bfaa89a56745cba8c7296529d2fc39830"


def _load_workflow(path: Path) -> dict[object, object]:
    _load()
    parser = importlib.import_module("ci_gap_workflow_parser")
    return parser._load_workflow(path)


def _bash_executable() -> str:
    candidates = [
        shutil.which("bash"),
        str(
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Git/bin/bash.exe"
        ),
    ]
    match = next(
        (
            candidate
            for candidate in candidates
            if candidate and Path(candidate).is_file()
        ),
        None,
    )
    if match is None:
        raise AssertionError("Bash is required to execute the NVD producer contract")
    return match


def _write_fake_gradlew(tmp_path: Path) -> None:
    gradlew = tmp_path / "gradlew"
    gradlew.write_text(
        """#!/usr/bin/env bash
set -u
if [[ " $* " != *" dependencyCheckUpdate "* ]]; then
  if [[ " $* " != *" dependencyCheckAggregate "* ]]; then
    echo "unexpected fake Gradle invocation: $*" >&2
    exit 97
  fi
  if [[ " $* " != *" -PdependencyCheckAutoUpdate=false "* ]]; then
    echo "aggregate did not disable updates: $*" >&2
    exit 98
  fi
  if [ -n "${NVD_API_KEY:-}" ]; then
    echo "aggregate inherited the NVD credential" >&2
    exit 99
  fi
  echo aggregate >> calls.log
  if [ "${FAKE_ANALYZE_RC:-0}" -ne 0 ]; then
    exit "${FAKE_ANALYZE_RC}"
  fi
  if [ "${FAKE_REPORT_MODE:-valid}" = "valid" ]; then
    mkdir -p build/reports
    printf '%s\n' \
      '{"dependencies":[{"projectReferences":["app:grayDebugRuntimeClasspath"]}]}' \
      > build/reports/dependency-check-report.json
  fi
  exit 0
fi
if [[ " $* " != *" -PdependencyCheckNvdValidForHours=0 "* ]]; then
  echo "update did not force a fresh NVD check: $*" >&2
  exit 96
fi
echo update >> calls.log
exit "${FAKE_UPDATE_RC:-0}"
""",
        encoding="utf-8",
        newline="\n",
    )
    gradlew.chmod(0o755)


@pytest.mark.parametrize(
    (
        "api_key",
        "update_rc",
        "analyze_rc",
        "report_mode",
        "existing_marker",
        "expected_rc",
        "expected_calls",
    ),
    [
        ("", 0, 0, "valid", None, 78, []),
        ("configured", 0, 0, "valid", None, 0, ["update", "aggregate"]),
        ("configured", 1, 0, "valid", "12345\n", 1, ["update"]),
        (
            "configured",
            0,
            1,
            "valid",
            "12345\n",
            1,
            ["update", "aggregate"],
        ),
        (
            "configured",
            0,
            0,
            "missing",
            "12345\n",
            1,
            ["update", "aggregate"],
        ),
    ],
)
def test_trusted_nvd_producer_publishes_marker_only_after_success(
    tmp_path: Path,
    api_key: str,
    update_rc: int,
    analyze_rc: int,
    report_mode: str,
    existing_marker: str | None,
    expected_rc: int,
    expected_calls: list[str],
) -> None:
    _write_fake_gradlew(tmp_path)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    refresh = scripts / "refresh_dependency_check_nvd.sh"
    shutil.copyfile(
        _ROOT / "android" / "scripts" / refresh.name,
        refresh,
    )
    shutil.copyfile(
        _ROOT / "android" / "scripts" / "verify_dependency_check_report.py",
        scripts / "verify_dependency_check_report.py",
    )
    marker = tmp_path / ".dependency-check-data" / "xpj-nvd-refresh-epoch"
    if existing_marker is not None:
        marker.parent.mkdir(parents=True)
        marker.write_text(existing_marker, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [_bash_executable(), refresh.as_posix()],
        cwd=tmp_path,
        env={
            **os.environ,
            "DEPENDENCY_CHECK_DATA_DIR": ".dependency-check-data",
            "NVD_API_KEY": api_key,
            "FAKE_UPDATE_RC": str(update_rc),
            "FAKE_ANALYZE_RC": str(analyze_rc),
            "FAKE_REPORT_MODE": report_mode,
            "PYTHON_BIN": sys.executable,
        },
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == expected_rc, result.stdout + result.stderr
    calls_path = tmp_path / "calls.log"
    actual_calls = (
        calls_path.read_text(encoding="utf-8").splitlines()
        if calls_path.is_file()
        else []
    )
    assert actual_calls == expected_calls
    if expected_rc == 0:
        assert marker.read_text(encoding="utf-8").strip().isdigit()
    elif existing_marker is not None:
        assert marker.read_text(encoding="utf-8") == existing_marker
    else:
        assert not marker.exists()


def test_nvd_producer_workflow_is_main_only_and_publishes_unique_cache() -> None:
    workflow = _load_workflow(
        _ROOT / ".github" / "workflows" / "android-nvd-cache.yml"
    )
    assert workflow["on"] == {"workflow_dispatch": None}
    assert set(workflow["jobs"]) == {"refresh", "verify"}
    refresh = workflow["jobs"]["refresh"]
    assert refresh["if"] == "github.ref == 'refs/heads/main'"
    assert refresh["timeout-minutes"] == 35
    assert refresh["outputs"] == {
        "cache-key": "${{ steps.nvd-cache.outputs.cache-key }}"
    }
    assert "NVD_API_KEY" not in refresh.get("env", {})
    steps = {step["name"]: step for step in refresh["steps"]}
    assert set(steps) == {
        "Checkout",
        "Set up Java",
        "Set up Gradle",
        "Prepare Android build",
        "Restore OWASP NVD database",
        "Refresh OWASP NVD database",
        "Save refreshed OWASP NVD database",
    }
    update = steps["Refresh OWASP NVD database"]
    assert update["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    assert (
        update["run"]
        == "timeout -k 1m 25m bash scripts/refresh_dependency_check_nvd.sh"
    )
    restore = steps["Restore OWASP NVD database"]
    save = steps["Save refreshed OWASP NVD database"]
    assert restore["id"] == "nvd-cache"
    assert restore["uses"] == "./.github/actions/restore-android-nvd"
    assert save["uses"] == f"actions/cache/save@{_CACHE_ACTION_SHA}"
    assert save["if"] == "${{ success() }}"
    assert save["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": "${{ steps.nvd-cache.outputs.cache-key }}",
    }
    for name, step in steps.items():
        serialized = json.dumps(step, sort_keys=True)
        if name == "Refresh OWASP NVD database":
            assert serialized.count("secrets.NVD_API_KEY") == 1
        else:
            assert "NVD_API_KEY" not in serialized

    verify = workflow["jobs"]["verify"]
    assert verify["needs"] == "refresh"
    assert verify["if"] == "github.ref == 'refs/heads/main'"
    assert verify["timeout-minutes"] == 20
    assert "NVD_API_KEY" not in json.dumps(verify, sort_keys=True)
    verify_steps = {step["name"]: step for step in verify["steps"]}
    assert set(verify_steps) == {
        "Checkout",
        "Set up Java",
        "Set up Gradle",
        "Prepare Android build",
        "Restore published OWASP NVD database",
        "Verify published OWASP NVD payload",
    }
    published_restore = verify_steps["Restore published OWASP NVD database"]
    assert published_restore["uses"] == (
        f"actions/cache/restore@{_CACHE_ACTION_SHA}"
    )
    assert published_restore["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": "${{ needs.refresh.outputs.cache-key }}",
        "fail-on-cache-miss": True,
    }
    payload = verify_steps["Verify published OWASP NVD payload"]["run"]
    assert "xpj-nvd-refresh-epoch" in payload
    assert "dependencyCheckAggregate -PdependencyCheckAutoUpdate=false" in (
        " ".join(payload.split())
    )
    assert "verify_dependency_check_report.py" in payload

    ci = _load_workflow(_ROOT / ".github" / "workflows" / "ci.yml")
    android_steps = {
        step["name"]: step for step in ci["jobs"]["android"]["steps"]
    }
    legacy_scan = android_steps[
        "Dependency vulnerability scan (OWASP dependency-check)"
    ]["run"]
    assert "dependencyCheckAggregate" in legacy_scan
    assert "dependencyCheckAnalyze" not in legacy_scan


def test_shared_nvd_restore_action_owns_the_producer_cache_identity() -> None:
    action = _load_workflow(
        _ROOT / ".github" / "actions" / "restore-android-nvd" / "action.yml"
    )
    assert action["outputs"]["cache-key"]["value"] == (
        "${{ steps.cache-key.outputs.value }}"
    )
    assert action["outputs"]["cache-generation"]["value"] == (
        "${{ steps.cache-key.outputs.generation }}"
    )
    steps = {step["name"]: step for step in action["runs"]["steps"]}
    assert set(steps) == {
        "Build NVD cache key",
        "Restore OWASP NVD database",
    }
    key = steps["Build NVD cache key"]
    assert key["id"] == "cache-key"
    assert key["shell"] == "bash"
    assert key["env"] == {
        "REPOSITORY_ROOT": "${{ github.workspace }}",
        "CACHE_OS": "${{ runner.os }}",
        "RUN_ID": "${{ github.run_id }}",
        "RUN_ATTEMPT": "${{ github.run_attempt }}",
    }
    assert (
        key["run"]
        == 'python3 "$REPOSITORY_ROOT/scripts/build_android_nvd_cache_key.py"'
    )

    restore = steps["Restore OWASP NVD database"]
    assert restore["id"] == "restore"
    assert restore["uses"] == f"actions/cache/restore@{_CACHE_ACTION_SHA}"
    assert restore["with"]["path"] == "~/.gradle/dependency-check-data"
    assert restore["with"]["key"] == "${{ steps.cache-key.outputs.value }}"
    restore_keys = restore["with"]["restore-keys"]
    assert (
        "nvd-${{ runner.os }}-"
        "${{ steps.cache-key.outputs.generation }}-"
        "${{ steps.cache-key.outputs.date }}-"
    ) in restore_keys
    assert restore_keys.rstrip().endswith(
        "nvd-${{ runner.os }}-${{ steps.cache-key.outputs.generation }}-"
    )
    for step in steps.values():
        uses = step.get("uses")
        if uses is not None:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses)


def test_nvd_cache_key_builder_executes_generation_contract(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "android" / "gradle" / "libs.versions.toml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        "[plugins]\n"
        'owasp-dependency-check = { id = "org.owasp.dependencycheck", '
        'version = "12.1.0" }\n',
        encoding="utf-8",
        newline="\n",
    )
    output = tmp_path / "github-output.txt"
    environment = {
        **os.environ,
        "REPOSITORY_ROOT": str(tmp_path),
        "CACHE_OS": "Linux",
        "RUN_ID": "123456",
        "RUN_ATTEMPT": "2",
        "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "build_android_nvd_cache_key.py"),
        ],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert outputs["generation"] == "dc-12.1.0-schema1"
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", outputs["date"])
    assert outputs["value"] == (
        "nvd-Linux-dc-12.1.0-schema1-"
        f"{outputs['date']}-123456-2"
    )

    catalog.write_text("[plugins]\n", encoding="utf-8", newline="\n")
    output.unlink()
    rejected = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "build_android_nvd_cache_key.py"),
        ],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert rejected.returncode != 0
    assert not output.exists()


def test_dependency_check_producer_contract_forces_real_refresh() -> None:
    build = (_ROOT / "android" / "build.gradle.kts").read_text(encoding="utf-8")
    for fragment in (
        "failOnError = true",
        'scanProjects = listOf(":app")',
        "autoUpdate = dependencyCheckAutoUpdate.get()",
        "providers.gradleProperty(\"dependencyCheckNvdValidForHours\")",
        "nvd.validForHours = dependencyCheckNvdValidForHours.get()",
    ):
        assert fragment in build
