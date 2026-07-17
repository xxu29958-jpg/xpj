from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests._infra.android_nvd_producer import assert_nvd_producer_workflow
from tests._infra.ci_gap import load_ci_gap_audit as _load

pytestmark = pytest.mark.parallel_safe

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_ACTION_SHA = "0057852bfaa89a56745cba8c7296529d2fc39830"


def _load_workflow(path: Path) -> dict[object, object]:
    _load()
    parser = importlib.import_module("ci_gap_workflow_parser")
    return parser._load_workflow(path)


def test_nvd_producer_workflow_stages_certifies_and_proves_trusted_cache() -> None:
    workflow = _load_workflow(
        _ROOT / ".github" / "workflows" / "android-nvd-cache.yml"
    )
    assert_nvd_producer_workflow(
        workflow,
        cache_action_sha=_CACHE_ACTION_SHA,
    )


def test_legacy_android_nvd_writer_is_serialized_and_keeps_secret_step_scoped() -> None:
    ci = _load_workflow(_ROOT / ".github" / "workflows" / "ci.yml")
    android = ci["jobs"]["android"]
    assert android["concurrency"] == {
        "group": "android-nvd-writer",
        "queue": "max",
    }
    assert "NVD_API_KEY" not in android.get("env", {})
    steps = {step["name"]: step for step in android["steps"]}
    detect = steps["Detect NVD credential"]
    assert detect["id"] == "nvd-credential"
    assert detect["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    scan = steps["Dependency vulnerability scan (OWASP dependency-check)"]
    assert scan["env"] == {"NVD_API_KEY": "${{ secrets.NVD_API_KEY }}"}
    scan_command = scan["run"]
    assert "dependencyCheckUpdate -PdependencyCheckNvdValidForHours=24" in (
        " ".join(scan_command.split())
    )
    assert (
        "dependencyCheckAggregate -PdependencyCheckAutoUpdate=false "
        "-PdependencyCheckNvdValidForHours=24"
    ) in " ".join(scan_command.split())
    assert "dependencyCheckValidateNvd" not in scan_command
    assert "-PnvdApiKey" not in scan_command
    serialized = json.dumps(android, sort_keys=True)
    assert serialized.count("secrets.NVD_API_KEY") == 2
    for name in (
        "NVD cache key (UTC date)",
        "Cache OWASP NVD database",
        "Dependency vulnerability scan (OWASP dependency-check)",
        "Enforce OWASP CVE findings (tolerate only NVD-data outages)",
    ):
        assert steps[name]["if"] == (
            "steps.nvd-credential.outputs.available == 'true'"
        )
    assert steps["Dependency vulnerability scan skipped"]["if"] == (
        "steps.nvd-credential.outputs.available != 'true'"
    )


def test_shared_nvd_restore_action_exposes_isolated_staging_identity() -> None:
    action = _load_workflow(
        _ROOT / ".github" / "actions" / "restore-android-nvd" / "action.yml"
    )
    _assert_restore_action_interface(action)
    _assert_restore_action_steps(action)


def _assert_restore_action_interface(action: dict[object, object]) -> None:
    assert action["inputs"] == {
        "required": {
            "description": "Fail when no trusted cache entry exists.",
            "required": False,
            "default": "false",
        }
    }
    assert action["outputs"] == {
        "cache-key": {
            "description": (
                "Unique key used when a trusted producer publishes refreshed data."
            ),
            "value": "${{ steps.cache-key.outputs.value }}",
        },
        "cache-generation": {
            "description": (
                "Dependency-check data generation accepted by this action."
            ),
            "value": "${{ steps.cache-key.outputs.generation }}",
        },
        "staging-cache-key": {
            "description": (
                "Isolated key used before a refreshed payload is certified."
            ),
            "value": "${{ steps.cache-key.outputs.staging-value }}",
        },
        "matched-cache-key": {
            "description": "Exact trusted cache key selected by the lookup.",
            "value": "${{ steps.lookup.outputs.cache-matched-key }}",
        },
        "cache-hit": {
            "description": (
                "Whether the selected trusted cache was restored exactly."
            ),
            "value": "${{ steps.restore.outputs.cache-hit }}",
        },
    }


def _assert_restore_action_steps(action: dict[object, object]) -> None:
    assert [step["name"] for step in action["runs"]["steps"]] == [
        "Build NVD cache key",
        "Find trusted OWASP NVD database",
        "Require a trusted OWASP NVD database",
        "Clear pre-existing OWASP NVD data",
        "Restore exact trusted OWASP NVD database",
        "Require the exact trusted cache entry",
    ]
    steps = {step["name"]: step for step in action["runs"]["steps"]}
    key = steps["Build NVD cache key"]
    assert key["id"] == "cache-key"
    assert key["shell"] == "bash"
    assert key["env"] == {
        "REPOSITORY_ROOT": "${{ github.workspace }}",
        "CACHE_OS": "${{ runner.os }}",
        "RUN_ID": "${{ github.run_id }}",
        "RUN_ATTEMPT": "${{ github.run_attempt }}",
    }
    assert key["run"] == (
        'python3 "$REPOSITORY_ROOT/scripts/build_android_nvd_cache_key.py"'
    )
    lookup = steps["Find trusted OWASP NVD database"]
    assert lookup["id"] == "lookup"
    assert lookup["uses"] == f"actions/cache/restore@{_CACHE_ACTION_SHA}"
    assert lookup["with"]["path"] == "~/.gradle/dependency-check-data"
    assert lookup["with"]["key"] == "${{ steps.cache-key.outputs.value }}"
    assert lookup["with"]["lookup-only"] is True
    restore_prefixes = lookup["with"]["restore-keys"].splitlines()
    assert restore_prefixes == [
        (
            "nvd-${{ runner.os }}-${{ steps.cache-key.outputs.generation }}-"
            "${{ steps.cache-key.outputs.date }}-"
        ),
        "nvd-${{ runner.os }}-${{ steps.cache-key.outputs.generation }}-",
    ]
    assert all(not prefix.startswith("nvd-staging-") for prefix in restore_prefixes)
    required = steps["Require a trusted OWASP NVD database"]
    assert required["if"] == (
        "inputs.required == 'true' && "
        "steps.lookup.outputs.cache-matched-key == ''"
    )
    assert "exit 1" in required["run"]
    clear = steps["Clear pre-existing OWASP NVD data"]
    assert clear["if"] == "steps.lookup.outputs.cache-matched-key != ''"
    assert clear["run"] == 'rm -rf "${HOME}/.gradle/dependency-check-data"'
    restore = steps["Restore exact trusted OWASP NVD database"]
    assert restore["if"] == "steps.lookup.outputs.cache-matched-key != ''"
    assert restore["id"] == "restore"
    assert restore["uses"] == f"actions/cache/restore@{_CACHE_ACTION_SHA}"
    assert restore["with"] == {
        "path": "~/.gradle/dependency-check-data",
        "key": "${{ steps.lookup.outputs.cache-matched-key }}",
        "fail-on-cache-miss": True,
    }
    exact = steps["Require the exact trusted cache entry"]
    assert exact["if"] == "steps.lookup.outputs.cache-matched-key != ''"
    assert exact["env"] == {"CACHE_HIT": "${{ steps.restore.outputs.cache-hit }}"}
    assert 'if [ "$CACHE_HIT" != "true" ]; then' in exact["run"]
    assert "exit 1" in exact["run"]
    for step in steps.values():
        uses = step.get("uses")
        if uses is not None:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses)


def test_nvd_cache_key_builder_separates_staging_from_trusted_namespace(
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
    suffix = (
        f"Linux-dc-12.1.0-schema1-{outputs['date']}-123456-2"
    )
    assert outputs["value"] == f"nvd-{suffix}"
    assert outputs["staging-value"] == f"nvd-staging-{suffix}"
    assert not outputs["staging-value"].startswith("nvd-Linux-")

    environment["CACHE_OS"] = "staging-Linux"
    output.unlink()
    ambiguous_os = subprocess.run(
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
    assert ambiguous_os.returncode != 0
    assert not output.exists()

    environment["CACHE_OS"] = "Linux"
    catalog.write_text("[plugins]\n", encoding="utf-8", newline="\n")
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


def test_dependency_check_policy_is_fixed_and_validation_is_task_scoped() -> None:
    build = (_ROOT / "android" / "build.gradle.kts").read_text(encoding="utf-8")
    for fragment in (
        "failOnError = true",
        'scanProjects = listOf(":app")',
        "autoUpdate = dependencyCheckAutoUpdate.get()",
        'providers.gradleProperty("dependencyCheckNvdValidForHours")',
        "hours == 0 || hours == 24",
        "nvd.validForHours = dependencyCheckNvdValidForHours.get()",
        "val dependencyCheckPolicyCvssThreshold = 7.0f",
        "val dependencyCheckPayloadValidationCvssThreshold = 11.0f",
        "requestedDependencyCheckTasks == listOf("
        '"dependencyCheckValidateNvd")',
        'tasks.register("verifyDependencyCheckContract")',
        'tasks.named("dependencyCheckUpdate")',
        'tasks.named("dependencyCheckAggregate")',
        'tasks.register("dependencyCheckValidateNvd")',
    ):
        assert fragment in build
    for forbidden in (
        'providers.gradleProperty("dependencyCheckFailBuildOnCvss")',
        'providers.gradleProperty("nvdApiKey")',
        'providers.environmentVariable("ORG_GRADLE_PROJECT_nvdApiKey")',
    ):
        assert forbidden not in build
