"""Read-only audit: CI invokes every pinned gradle task / pytest lane."""

from __future__ import annotations

import pathlib
import sys

from ci_audit_provider import (
    PLATFORM_WORKFLOW_PARTS,
    selected_ci_platforms,
    workflow_dirs_for_platforms,
)
from ci_gap_action_pins import (
    github_external_uses_pin_violations as _github_external_uses_pin_violations,
)
from ci_gap_command_contract import (
    REQUIRED_GRADLE_TASKS,
    GradleInvocation,
    _gradle_invocation_has_tokens,
    _iter_executable_command_segments,
    _iter_gradle_invocations,
)
from ci_gap_command_contract import (
    _missing_gradle_tasks as _command_missing_gradle_tasks,
)
from ci_gap_installer_artifact import (
    missing_installer_hash_dataflow_by_platform as _evaluate_installer_hash_dataflow,
)
from ci_gap_installer_artifact import (
    missing_installer_publish_actions_by_platform as _evaluate_installer_publish_actions,
)
from ci_gap_release_scope import release_apk_scope_policy_violations
from ci_gap_required_commands import REQUIRED_CI_INVOCATIONS, REQUIRED_CI_INVOCATIONS_BY_PLATFORM
from ci_gap_workflow_parser import (
    WorkflowAction,
    WorkflowCommand,
    _iter_workflow_actions,
    _iter_workflow_run_commands,
    _locate_workflow_dirs,
)

REQUIRED_GRADLE_TASKS_BY_PLATFORM = {
    "GitHub": tuple(REQUIRED_GRADLE_TASKS),
    "Gitea": tuple(REQUIRED_GRADLE_TASKS),
}
PATH_SCOPED_RELEASE_TASKS = frozenset(
    {":app:assembleGrayRelease", ":app:assembleInternalRelease"}
)
_missing_gradle_tasks = _command_missing_gradle_tasks
_CI_INVOCATION_SCOPES = {
    "pytest ordinary business lane": {"full", "postgres"},
    "pytest real-db serial lane": {"full", "postgres"},
    "end-to-end smoke": {"full", "postgres"},
    "backup/restore drill": {"full", "postgres"},
    "pytest installer safety lane": {"full", "windows"},
    "pytest installer resource-serial lane": {"full", "windows"},
    "installer source preflight (Windows PowerShell 5.1)": {"full", "windows"},
    "installer source preflight (PowerShell 7)": {"full", "windows"},
    "frozen backend locked release build": {"full", "windows"},
    "authoritative Inno installer compile": {"full", "windows"},
    "atomic installer publish-unit verification": {"full", "windows"},
    "desktop compileall": {"full", "desktop"},
    "desktop ruff lint": {"full", "desktop"},
    "desktop pytest": {"full", "desktop"},
}

def _commands_for_platform(commands: list[WorkflowCommand], platform: str) -> list[WorkflowCommand]:
    return [command for command in commands if PLATFORM_WORKFLOW_PARTS[platform] in command.workflow.parts]


def _missing_gradle_tasks_by_platform(
    commands: list[WorkflowCommand],
    *,
    path_scoped_commands: list[WorkflowCommand] | None = None,
    platforms: tuple[str, ...] = tuple(PLATFORM_WORKFLOW_PARTS),
) -> list[str]:
    missing: list[str] = []
    scoped_commands = path_scoped_commands if path_scoped_commands is not None else commands
    for platform in platforms:
        required_tasks = REQUIRED_GRADLE_TASKS_BY_PLATFORM[platform]
        platform_commands = _commands_for_platform(commands, platform)
        platform_scoped_commands = _commands_for_platform(scoped_commands, platform)
        for task in required_tasks:
            task_commands = (
                platform_scoped_commands
                if task in PATH_SCOPED_RELEASE_TASKS
                else platform_commands
            )
            allowed_scopes = {"full", "android"}
            task_commands = [
                command
                for command in task_commands
                if command.protection_scope in allowed_scopes
            ]
            invocations = _iter_gradle_invocations(task_commands)
            required_tokens = tuple(task.split())
            if not any(
                _gradle_invocation_has_tokens(invocation, required_tokens)
                for invocation in invocations
            ):
                missing.append(f"{platform}: {task}")
    return missing


def _missing_ci_invocations(commands: list[WorkflowCommand]) -> list[str]:
    missing: list[str] = []
    for required in REQUIRED_CI_INVOCATIONS:
        allowed_scopes = _CI_INVOCATION_SCOPES.get(required.label, {"full"})
        executable_segments = _iter_executable_command_segments(
            [
                command
                for command in commands
                if command.protection_scope in allowed_scopes
                and required.matches_environment(command.environment)
            ]
        )
        if not any(required.matches(segment) for segment in executable_segments):
            missing.append(required.label)
    return missing


def _missing_ci_invocations_by_platform(
    commands: list[WorkflowCommand],
    *,
    platforms: tuple[str, ...] = tuple(PLATFORM_WORKFLOW_PARTS),
) -> list[str]:
    missing: list[str] = []
    for platform in platforms:
        platform_commands = _commands_for_platform(commands, platform)
        for label in _missing_ci_invocations(platform_commands):
            missing.append(f"{platform}: {label}")
        for required in REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform]:
            allowed_scopes = _CI_INVOCATION_SCOPES.get(required.label, {"full"})
            executable_segments = _iter_executable_command_segments(
                [
                    command
                    for command in platform_commands
                    if command.protection_scope in allowed_scopes
                    and required.matches_environment(command.environment)
                ]
            )
            if not any(required.matches(segment) for segment in executable_segments):
                missing.append(f"{platform}: {required.label}")
    return missing


def _missing_installer_hash_dataflow_by_platform(
    commands: list[WorkflowCommand],
    *,
    platforms: tuple[str, ...] = tuple(PLATFORM_WORKFLOW_PARTS),
) -> list[str]:
    return _evaluate_installer_hash_dataflow(
        commands,
        segment_reader=_iter_executable_command_segments,
        platforms=platforms,
    )


def _missing_installer_publish_actions_by_platform(
    commands: list[WorkflowCommand],
    actions: list[WorkflowAction],
    *,
    platforms: tuple[str, ...] = tuple(PLATFORM_WORKFLOW_PARTS),
) -> list[str]:
    return _evaluate_installer_publish_actions(
        commands,
        actions,
        segment_reader=_iter_executable_command_segments,
        platforms=platforms,
    )


def _is_github_workflow(path: pathlib.Path) -> bool:
    return ".github" in path.parts and "workflows" in path.parts


def _is_gitea_workflow(path: pathlib.Path) -> bool:
    return ".gitea" in path.parts and "workflows" in path.parts


def _has_bounded_release_workers(tokens: tuple[str, ...]) -> bool:
    limits: list[int] = []
    for index, token in enumerate(tokens):
        raw: str | None = None
        if token.startswith("--max-workers="):
            raw = token.partition("=")[2]
        elif token == "--max-workers" and index + 1 < len(tokens):
            raw = tokens[index + 1]
        if raw is not None:
            try:
                limits.append(int(raw))
            except ValueError:
                return False
    return len(limits) == 1 and 1 <= limits[0] <= 2


def _is_release_apk_invocation(invocation: GradleInvocation) -> bool:
    return _gradle_invocation_has_tokens(
        invocation,
        (":app:assembleGrayRelease", ":app:assembleInternalRelease"),
    )


def _github_ci_release_apk_policy_violations(commands: list[WorkflowCommand]) -> list[str]:
    github_gradle_invocations = [
        invocation
        for invocation in _iter_gradle_invocations(commands)
        if _is_github_workflow(invocation.workflow)
    ]
    all_github_gradle_invocations = [
        invocation
        for invocation in _iter_gradle_invocations(
            commands, require_failure_propagation=False
        )
        if _is_github_workflow(invocation.workflow)
    ]
    violations: list[str] = []
    if not any(
        _is_release_apk_invocation(invocation)
        and _has_bounded_release_workers(invocation.tokens)
        for invocation in github_gradle_invocations
    ):
        violations.append(
            "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
        )
    if any("--stop" in invocation.tokens for invocation in all_github_gradle_invocations):
        violations.append("GitHub CI must not call gradlew --stop during Android lanes")
    return violations


def _gitea_ci_release_apk_policy_violations(commands: list[WorkflowCommand]) -> list[str]:
    gitea_gradle_invocations = [
        invocation
        for invocation in _iter_gradle_invocations(commands)
        if _is_gitea_workflow(invocation.workflow)
    ]
    if any(
        _is_release_apk_invocation(invocation)
        and _has_bounded_release_workers(invocation.tokens)
        for invocation in gitea_gradle_invocations
    ):
        return []
    return [
        "Gitea Android release APK builds must run gray/internal release tasks in one bounded-worker Gradle invocation"
    ]


def _missing_selected_workflow_directory(
    workflow_dirs: list[pathlib.Path],
    platforms: tuple[str, ...],
) -> str | None:
    for platform in platforms:
        workflow_part = PLATFORM_WORKFLOW_PARTS[platform]
        if not any(
            workflow_part in path.parts and "workflows" in path.parts
            for path in workflow_dirs
        ):
            return workflow_part
    return None


def _selected_provider_policy_violations(
    path_scoped_commands: list[WorkflowCommand],
    workflow_dirs: list[pathlib.Path],
    platforms: tuple[str, ...],
) -> list[str]:
    violations: list[str] = []
    if "GitHub" in platforms:
        violations.extend(_github_ci_release_apk_policy_violations(path_scoped_commands))
        violations.extend(_github_external_uses_pin_violations(workflow_dirs))
    if "Gitea" in platforms:
        violations.extend(_gitea_ci_release_apk_policy_violations(path_scoped_commands))
    violations.extend(
        release_apk_scope_policy_violations(
            {command.workflow for command in path_scoped_commands},
            platforms=platforms,
        )
    )
    return violations


def _collect_missing_contracts(
    commands: list[WorkflowCommand],
    actions: list[WorkflowAction],
    path_scoped_commands: list[WorkflowCommand],
    workflow_dirs: list[pathlib.Path],
    platforms: tuple[str, ...],
) -> list[str]:
    missing = [
        f"gradle task: {task}"
        for task in _missing_gradle_tasks_by_platform(
            commands,
            path_scoped_commands=path_scoped_commands,
            platforms=platforms,
        )
    ]
    missing.extend(
        f"ci invocation: {invocation}"
        for invocation in _missing_ci_invocations_by_platform(
            commands,
            platforms=platforms,
        )
    )
    missing.extend(
        f"ci dataflow: {dataflow}"
        for dataflow in _missing_installer_hash_dataflow_by_platform(
            commands,
            platforms=platforms,
        )
    )
    missing.extend(
        f"ci action: {action}"
        for action in _missing_installer_publish_actions_by_platform(
            commands,
            actions,
            platforms=platforms,
        )
    )
    missing.extend(
        f"ci policy: {violation}"
        for violation in _selected_provider_policy_violations(
            path_scoped_commands,
            workflow_dirs,
            platforms,
        )
    )
    return missing


def main() -> int:
    try:
        platforms = selected_ci_platforms()
    except ValueError as exc:
        print(f"CI gap audit: FAIL - {exc}")
        return 1
    workflow_dirs = workflow_dirs_for_platforms(_locate_workflow_dirs(), platforms)
    if not workflow_dirs:
        print("CI gap audit: FAIL - no selected Actions workflow directory found")
        return 1

    workflow_labels = ", ".join(str(path) for path in workflow_dirs)
    missing_workflow_part = _missing_selected_workflow_directory(workflow_dirs, platforms)
    if missing_workflow_part is not None:
        print(f"CI gap audit: FAIL - {missing_workflow_part}/workflows/ directory not found")
        return 1

    commands = _iter_workflow_run_commands(workflow_dirs, protected_only=True)
    actions = _iter_workflow_actions(workflow_dirs, protected_only=True)
    path_scoped_commands = _iter_workflow_run_commands(workflow_dirs)
    missing = _collect_missing_contracts(
        commands,
        actions,
        path_scoped_commands,
        workflow_dirs,
        platforms,
    )

    if missing:
        print("=== CI gap audit: FAIL ===")
        for entry in missing:
            print(f"  missing from required platform workflow set: {entry}")
        return 1

    print(
        f"=== CI gap audit: OK ({len(REQUIRED_GRADLE_TASKS)} gradle tasks + "
        f"{len(REQUIRED_CI_INVOCATIONS)} backend invocations per selected platform + release APK "
        f"+ installer artifact and provider-specific policies verified across "
        f"Actions workflows: {workflow_labels}) ==="
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
