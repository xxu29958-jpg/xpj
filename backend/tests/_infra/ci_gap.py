"""Loader for the standalone CI-gap audit module used by contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "_audit_ci_gap.py"
_CONNECTED_TASK = ":app:connectedGrayDebugAndroidTest"


def load_ci_gap_audit() -> object:
    old_path = list(sys.path)
    module_dir = str(_MODULE_PATH.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    try:
        spec = importlib.util.spec_from_file_location("_audit_ci_gap", _MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old_path


def _write_connected_workflow(workflow: Path, script: str) -> None:
    workflow.write_text(
        f"""
name: connected
on: pull_request
jobs:
  connected:
    steps:
      - uses: reactivecircus/android-emulator-runner@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
        with:
          working-directory: android
          script: >-
            {script}
""",
        encoding="utf-8",
    )


def _connected_task_is_missing(mod: object, workflows: Path) -> bool:
    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
    return _CONNECTED_TASK in mod._missing_gradle_tasks(commands)


def _assert_multiline_action_script_is_rejected(
    mod: object,
    workflows: Path,
    workflow: Path,
) -> None:
    workflow.write_text(
        """
name: connected
on: pull_request
jobs:
  connected:
    steps:
      - uses: reactivecircus/android-emulator-runner@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
        with:
          working-directory: android
          script: |
            false
            timeout 14m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest
""",
        encoding="utf-8",
    )
    assert _connected_task_is_missing(mod, workflows)


def assert_ci_gap_requires_single_direct_action_command(
    mod: object,
    tmp_path: Path,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    workflow = workflows / "android-connected-test.yml"
    direct_command = (
        "timeout --signal=INT --kill-after=30s 14m "
        f"./gradlew --no-daemon {_CONNECTED_TASK}"
    )
    _write_connected_workflow(
        workflow,
        direct_command,
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert len(commands) == 1
    assert commands[0].text.strip() == direct_command
    assert _CONNECTED_TASK not in mod._missing_gradle_tasks(commands)

    for indirect_command in (
        "/bin/sh scripts/run_connected_ci.sh",
        f"set -n; {direct_command}",
        f'finish=exit; "$finish" 0; {direct_command}',
    ):
        _write_connected_workflow(workflow, indirect_command)
        assert _connected_task_is_missing(mod, workflows)
    _assert_multiline_action_script_is_rejected(mod, workflows, workflow)


def assert_ci_provider_selection_contract(mod: object) -> None:
    assert mod.selected_ci_platforms({}) == ("GitHub", "Gitea")
    assert mod.selected_ci_platforms({"XPJ_CI_AUDIT_PROVIDER": "github"}) == (
        "GitHub",
    )
    github_runtime = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "XPJ_CI_AUDIT_PROVIDER": "github",
    }
    assert mod.selected_ci_platforms(github_runtime) == ("GitHub",)
    with pytest.raises(ValueError, match="does not match GitHub runtime"):
        mod.selected_ci_platforms(
            {**github_runtime, "XPJ_CI_AUDIT_PROVIDER": "gitea"}
        )

    gitea_runtime = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITEA_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://git.example.test",
        "XPJ_CI_AUDIT_PROVIDER": "gitea",
    }
    assert mod.selected_ci_platforms(gitea_runtime) == ("Gitea",)
    with pytest.raises(ValueError, match="does not match Gitea runtime"):
        mod.selected_ci_platforms(
            {**gitea_runtime, "XPJ_CI_AUDIT_PROVIDER": "github"}
        )
    with pytest.raises(ValueError, match="conflicting GitHub/Gitea"):
        mod.selected_ci_platforms(
            {**gitea_runtime, "GITHUB_SERVER_URL": "https://github.com"}
        )
    with pytest.raises(ValueError, match="required in CI"):
        mod.selected_ci_platforms(
            {
                key: value
                for key, value in github_runtime.items()
                if key != "XPJ_CI_AUDIT_PROVIDER"
            }
        )
