from __future__ import annotations

import importlib
import os
import shutil
import subprocess
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
  echo "unexpected fake Gradle invocation: $*" >&2
  exit 97
fi
echo update >> calls.log
exit "${FAKE_UPDATE_RC:-0}"
""",
        encoding="utf-8",
        newline="\n",
    )
    gradlew.chmod(0o755)


@pytest.mark.parametrize(
    ("api_key", "update_rc", "existing_marker", "expected_rc", "expected_calls"),
    [
        ("", 0, None, 78, []),
        ("configured", 0, None, 0, ["update"]),
        ("configured", 1, "12345\n", 1, ["update"]),
    ],
)
def test_trusted_nvd_producer_publishes_marker_only_after_success(
    tmp_path: Path,
    api_key: str,
    update_rc: int,
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
    if api_key and update_rc == 0:
        assert marker.read_text(encoding="utf-8").strip().isdigit()
    elif existing_marker is not None:
        assert marker.read_text(encoding="utf-8") == existing_marker
    else:
        assert not marker.exists()


def test_nvd_producer_workflow_is_main_only_and_publishes_unique_cache() -> None:
    workflow = _load_workflow(
        _ROOT / ".github" / "workflows" / "android-nvd-cache.yml"
    )
    assert workflow["on"] == {
        "schedule": [{"cron": "17 2 * * *"}],
        "workflow_dispatch": None,
    }
    refresh = workflow["jobs"]["refresh"]
    assert refresh["if"] == "github.ref == 'refs/heads/main'"
    assert refresh["timeout-minutes"] == 35
    assert "NVD_API_KEY" not in refresh.get("env", {})
    steps = {step["name"]: step for step in refresh["steps"]}
    update = steps["Refresh OWASP NVD database"]
    assert update["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    assert (
        update["run"]
        == "timeout -k 1m 25m bash scripts/refresh_dependency_check_nvd.sh"
    )
    restore = steps["Restore OWASP NVD database"]
    save = steps["Save refreshed OWASP NVD database"]
    assert restore["uses"] == f"actions/cache/restore@{_CACHE_ACTION_SHA}"
    assert save["uses"] == f"actions/cache/save@{_CACHE_ACTION_SHA}"
    assert restore["with"]["path"] == save["with"]["path"]
    assert restore["with"]["key"] == save["with"]["key"]
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in save["with"]["key"]


def test_dependency_check_producer_contract_forces_real_refresh() -> None:
    build = (_ROOT / "android" / "build.gradle.kts").read_text(encoding="utf-8")
    for fragment in (
        "failOnError = true",
        'scanProjects = listOf(":app")',
        "autoUpdate = dependencyCheckAutoUpdate.get()",
        "nvd.validForHours = 0",
    ):
        assert fragment in build
