from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests._infra.android_gradle_cache import (
    assert_github_gradle_cache_topology,
)
from tests._infra.android_nvd_producer import (
    assert_legacy_nvd_consumer_job,
    assert_nvd_producer_workflow,
    assert_runtime_dependency_suppressions,
)
from tests._infra.ci_gap import load_ci_gap_audit as _load

pytestmark = pytest.mark.parallel_safe

_ROOT = Path(__file__).resolve().parents[2]
_DOWNLOAD_ACTION_SHA = "d3f86a106a0bac45b974a628896c90dbdf5c8093"
_UPLOAD_ACTION_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def _load_workflow(path: Path) -> dict[object, object]:
    _load()
    parser = importlib.import_module("ci_gap_workflow_parser")
    return parser._load_workflow(path)


def _load_script(path: Path, *, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nvd_producer_workflow_stages_certifies_and_publishes_artifact() -> None:
    workflow = _load_workflow(
        _ROOT / ".github" / "workflows" / "android-nvd-cache.yml"
    )
    assert_nvd_producer_workflow(
        workflow,
        download_action_sha=_DOWNLOAD_ACTION_SHA,
        upload_action_sha=_UPLOAD_ACTION_SHA,
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


def test_legacy_android_nvd_transition_and_cache_authority_are_explicit() -> None:
    ci = _load_workflow(_ROOT / ".github" / "workflows" / "ci.yml")
    assert_legacy_nvd_consumer_job(ci["jobs"]["android"])
    workflows = {
        path.name: _load_workflow(path)
        for path in (_ROOT / ".github" / "workflows").glob("*.yml")
    }
    assert_github_gradle_cache_topology(workflows)
    gitea = _load_workflow(
        _ROOT / ".gitea" / "workflows" / "windows-ci.yml"
    )
    assert gitea["jobs"]["android-unit"]["env"]["GRADLE_OPTS"] == (
        "-Dorg.gradle.caching=false"
    )


def test_legacy_android_nvd_failures_are_not_adjudicated_from_logs() -> None:
    ci = _load_workflow(_ROOT / ".github" / "workflows" / "ci.yml")
    android = ci["jobs"]["android"]
    steps = {step["name"]: step for step in android["steps"]}
    scan = steps["Dependency vulnerability scan (OWASP dependency-check)"]
    serialized = json.dumps(android, sort_keys=True)
    assert "continue-on-error" not in scan
    assert "steps.owasp.outcome" not in serialized
    assert "OWASP_NVD_UPDATE_TIMED_OUT" not in serialized
    assert "OWASP_ANALYZE_TIMED_OUT" not in serialized
    assert "NoDataException" not in serialized
    assert "No documents exist" not in serialized


def _assert_restore_action_interface(action: dict[object, object]) -> None:
    assert action["inputs"] == {
        "github-token": {
            "description": (
                "Token with read access to workflow runs and artifacts."
            ),
            "required": True,
        },
        "required": {
            "description": "Fail when no certified producer artifact exists.",
            "required": False,
            "default": "false",
        },
        "allow-expired": {
            "description": (
                "Allow expired data only as a protected producer refresh seed."
            ),
            "required": False,
            "default": "false",
        },
    }
    outputs = action["outputs"]
    assert outputs["artifact-name"]["value"] == (
        "${{ steps.select.outputs.artifact-name }}"
    )
    assert outputs["publication-artifact-name"]["value"] == (
        "${{ steps.identity.outputs.artifact-name }}"
    )
    assert outputs["producer-run-id"]["value"] == (
        "${{ steps.select.outputs.run-id }}"
    )
    assert outputs["staging-artifact-name"]["value"] == (
        "${{ steps.identity.outputs.staging-artifact-name }}"
    )
    assert outputs["restored"]["value"] == "${{ steps.select.outputs.found }}"
    assert outputs["payload-sha256"]["value"] == (
        "${{ steps.verify.outputs.payload-sha256 }}"
    )


def _assert_restore_action_trust_chain(action: dict[object, object]) -> None:
    steps = {step["name"]: step for step in action["runs"]["steps"]}
    assert list(steps) == [
        "Build NVD publication identity",
        "Select latest certified producer artifact",
        "Clear artifact staging paths",
        "Require certified producer artifact",
        "Download certified producer artifact",
        "Install certified producer artifact",
        "Verify certified producer artifact",
    ]
    identity = steps["Build NVD publication identity"]
    assert identity["run"] == (
        "python3 "
        '"$REPOSITORY_ROOT/scripts/build_android_nvd_identity.py"'
    )
    select = steps["Select latest certified producer artifact"]
    assert select["env"] == {
        "GITHUB_TOKEN": "${{ inputs.github-token }}",
        "DEFAULT_BRANCH": "${{ github.event.repository.default_branch }}",
        "NVD_WORKFLOW": "android-nvd-cache.yml",
        "NVD_ARTIFACT_PREFIX": (
            "${{ steps.identity.outputs.artifact-prefix }}"
        ),
    }
    assert "select_android_nvd_artifact.py" in select["run"]
    clear = steps["Clear artifact staging paths"]
    assert "if" not in clear
    assert "${RUNNER_TEMP}/android-nvd-payload" in clear["run"]
    assert "${HOME}/.gradle/dependency-check-data" in clear["run"]
    required = steps["Require certified producer artifact"]
    assert required["if"] == (
        "inputs.required == 'true' && steps.select.outputs.found != 'true'"
    )
    download = steps["Download certified producer artifact"]
    assert download["uses"] == (
        f"actions/download-artifact@{_DOWNLOAD_ACTION_SHA}"
    )
    assert download["with"] == {
        "name": "${{ steps.select.outputs.artifact-name }}",
        "path": "${{ runner.temp }}/android-nvd-payload",
        "github-token": "${{ inputs.github-token }}",
        "repository": "${{ github.repository }}",
        "run-id": "${{ steps.select.outputs.run-id }}",
    }
    verify = steps["Verify certified producer artifact"]
    assert verify["id"] == "verify"
    assert "--allow-expired" in verify["run"]
    serialized = json.dumps(action, sort_keys=True)
    assert "actions/cache" not in serialized
    assert "restore-keys" not in serialized
    for step in steps.values():
        uses = step.get("uses")
        if uses is not None:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses)


def test_shared_nvd_restore_action_uses_only_successful_main_run_artifacts() -> None:
    action = _load_workflow(
        _ROOT / ".github" / "actions" / "restore-android-nvd" / "action.yml"
    )
    _assert_restore_action_interface(action)
    _assert_restore_action_trust_chain(action)


def _copy_producer_contract(tmp_path: Path) -> ModuleType:
    contract = _load_script(
        _ROOT / "android" / "scripts" / "dependency_check_contract.py",
        name="nvd_contract_fixture",
    )
    for relative in contract.producer_contract_paths(_ROOT):
        source = _ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return contract


def _run_identity(tmp_path: Path, *, output_name: str = "output.txt") -> dict[str, str]:
    output = tmp_path / output_name
    result = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "build_android_nvd_identity.py"),
        ],
        env={
            **os.environ,
            "REPOSITORY_ROOT": str(tmp_path),
            "CACHE_OS": "Linux",
            "RUN_ID": "123456",
            "RUN_ATTEMPT": "2",
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )


def test_publication_identity_binds_every_authority_contract_file(
    tmp_path: Path,
) -> None:
    _copy_producer_contract(tmp_path)
    first = _run_identity(tmp_path, output_name="first.txt")
    assert re.fullmatch(r"[0-9a-f]{64}", first["contract-sha256"])
    assert first["generation"] == (
        "dc-12.1.0-schema2-" + first["contract-sha256"]
    )
    suffix = f"Linux-{first['generation']}-123456-2"
    assert first["artifact-name"] == f"android-nvd-{suffix}"
    assert first["artifact-prefix"] == f"android-nvd-Linux-{first['generation']}-"
    assert first["staging-artifact-name"] == f"nvd-staging-{suffix}"

    certifier = (
        tmp_path / "android" / "scripts" / "certify_dependency_check_nvd_payload.sh"
    )
    certifier.write_text(
        certifier.read_text(encoding="utf-8") + "\n# contract mutation\n",
        encoding="utf-8",
        newline="\n",
    )
    second = _run_identity(tmp_path, output_name="second.txt")
    assert second["contract-sha256"] != first["contract-sha256"]
    assert second["artifact-name"] != first["artifact-name"]
    assert second["staging-artifact-name"] != first["staging-artifact-name"]

    wrapper = tmp_path / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties"
    wrapper.write_text(
        wrapper.read_text(encoding="utf-8") + "\n# wrapper mutation\n",
        encoding="utf-8",
        newline="\n",
    )
    third = _run_identity(tmp_path, output_name="third.txt")
    assert third["contract-sha256"] != second["contract-sha256"]
    assert third["artifact-name"] != second["artifact-name"]


def _trusted_run(*, run_id: int, attempt: int = 1) -> dict[str, object]:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "event": "schedule",
        "path": ".github/workflows/android-nvd-cache.yml",
        "head_repository": {"full_name": "xxu29958-jpg/xpj"},
    }


def test_artifact_selector_rejects_pr_failed_and_wrong_contract_sources() -> None:
    selector = _load_script(
        _ROOT / "scripts" / "select_android_nvd_artifact.py",
        name="nvd_artifact_selector",
    )
    prefix = "android-nvd-Linux-dc-12.1.0-schema2-current-"
    pull_request = {
        **_trusted_run(run_id=30),
        "head_branch": "feature",
        "event": "pull_request",
    }
    failed = {**_trusted_run(run_id=29), "conclusion": "failure"}
    accepted = _trusted_run(run_id=28, attempt=3)
    selected = selector.select_artifact(
        runs=[pull_request, failed, accepted],
        artifacts_by_run={
            30: [
                {
                    "id": 300,
                    "name": f"{prefix}30-1",
                    "expired": False,
                    "digest": f"sha256:{'a' * 64}",
                }
            ],
            29: [
                {
                    "id": 290,
                    "name": f"{prefix}29-1",
                    "expired": False,
                    "digest": f"sha256:{'b' * 64}",
                }
            ],
            28: [
                {
                    "id": 281,
                    "name": "android-nvd-Linux-dc-old-contract-28-3",
                    "expired": False,
                    "digest": f"sha256:{'c' * 64}",
                },
                {
                    "id": 282,
                    "name": f"{prefix}28-3",
                    "expired": False,
                    "created_at": "2026-07-18T01:00:00Z",
                    "digest": f"sha256:{'d' * 64}",
                },
            ],
        },
        repository="xxu29958-jpg/xpj",
        default_branch="main",
        artifact_prefix=prefix,
    )
    assert selected == (28, f"{prefix}28-3", 282, f"sha256:{'d' * 64}")


def test_artifact_selector_accepts_available_attempt_after_partial_rerun() -> None:
    selector = _load_script(
        _ROOT / "scripts" / "select_android_nvd_artifact.py",
        name="nvd_partial_rerun_selector",
    )
    prefix = "android-nvd-Linux-dc-12.1.0-schema2-current-"
    selected = selector.select_artifact(
        runs=[_trusted_run(run_id=41, attempt=2)],
        artifacts_by_run={
            41: [
                {
                    "id": 411,
                    "name": f"{prefix}41-1",
                    "expired": False,
                    "created_at": "2026-07-18T01:00:00Z",
                    "digest": f"sha256:{'e' * 64}",
                }
            ]
        },
        repository="xxu29958-jpg/xpj",
        default_branch="main",
        artifact_prefix=prefix,
    )
    assert selected == (41, f"{prefix}41-1", 411, f"sha256:{'e' * 64}")


def test_artifact_selector_uses_artifact_freshness_not_api_run_order() -> None:
    selector = _load_script(
        _ROOT / "scripts" / "select_android_nvd_artifact.py",
        name="nvd_fresh_artifact_selector",
    )
    prefix = "android-nvd-Linux-dc-12.1.0-schema2-current-"
    selected = selector.select_artifact(
        runs=[_trusted_run(run_id=50), _trusted_run(run_id=49)],
        artifacts_by_run={
            50: [
                {
                    "id": 501,
                    "name": f"{prefix}50-1",
                    "expired": False,
                    "created_at": "2026-07-18T01:00:00Z",
                    "digest": f"sha256:{'f' * 64}",
                }
            ],
            49: [
                {
                    "id": 491,
                    "name": f"{prefix}49-1",
                    "expired": False,
                    "created_at": "2026-07-18T02:00:00Z",
                    "digest": f"sha256:{'a' * 64}",
                }
            ],
        },
        repository="xxu29958-jpg/xpj",
        default_branch="main",
        artifact_prefix=prefix,
    )
    assert selected == (49, f"{prefix}49-1", 491, f"sha256:{'a' * 64}")


def test_publication_ref_guard_is_behavioral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_script(
        _ROOT / "scripts" / "verify_android_nvd_publication_ref.py",
        name="nvd_publication_ref_guard",
    )
    current_sha = "a" * 40
    monkeypatch.setattr(
        guard,
        "_current_default_sha",
        lambda **_kwargs: current_sha,
    )
    for key, value in {
        "REQUESTED_REF": "refs/heads/main",
        "REQUESTED_SHA": current_sha,
        "DEFAULT_BRANCH": "main",
        "GITHUB_API_URL": "https://api.github.test",
        "GITHUB_REPOSITORY": "xxu29958-jpg/xpj",
        "GITHUB_TOKEN": "test-token",
    }.items():
        monkeypatch.setenv(key, value)
    assert guard.main() == 0

    monkeypatch.setenv("REQUESTED_SHA", "b" * 40)
    with pytest.raises(ValueError, match="current default-branch tip"):
        guard.main()

    monkeypatch.setenv("REQUESTED_SHA", current_sha)
    monkeypatch.setenv("REQUESTED_REF", "refs/heads/feature")
    with pytest.raises(ValueError, match="restricted"):
        guard.main()


def test_dependency_check_policy_is_fixed_and_validation_is_task_scoped() -> None:
    build = (_ROOT / "android" / "build.gradle.kts").read_text(encoding="utf-8")
    for fragment in (
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
        'providers.gradleProperty("dependencyCheckNvdValidForHours")',
        "hours == 0 || hours == 24",
        "nvd.validForHours = dependencyCheckNvdValidForHours.get()",
        "val dependencyCheckPolicyCvssThreshold = 7.0f",
        "val dependencyCheckPayloadValidationCvssThreshold = 11.0f",
        'dependencyCheck.failBuildOnCVSS == 11.0f',
        'dependencyCheck.failBuildOnCVSS == 7.0f',
        "dependencyCheck.scanConfigurations ==",
        "dependencyCheckRuntimeConfigurations",
        'dependencyCheck.analyzers.ossIndex.enabled == false',
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
    assert_runtime_dependency_suppressions(
        _ROOT / "android" / "config" / "dependency-check" / "suppressions.xml"
    )
