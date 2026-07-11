"""Read-only audit: CI invokes every pinned gradle task / pytest lane."""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass

from ci_gap_action_pins import (
    github_external_uses_pin_violations as _github_external_uses_pin_violations,
)
from ci_gap_powershell import (
    catch_blocks_propagate_failure as _catch_blocks_propagate_failure,
)
from ci_gap_powershell import contains_catch_block as _contains_catch_block
from ci_gap_powershell import (
    is_native_failure_propagation_guard as _is_native_failure_propagation_guard,
)
from ci_gap_release_scope import release_apk_scope_policy_violations
from ci_gap_required_commands import (
    REQUIRED_CI_INVOCATIONS,
    REQUIRED_CI_INVOCATIONS_BY_PLATFORM,
)
from ci_gap_shell import (
    has_unquoted_shell_separator as _has_unquoted_shell_separator,
)
from ci_gap_shell import (
    is_output_command as _is_output_command,
)
from ci_gap_shell import (
    shell_tokens as _shell_tokens,
)
from ci_gap_shell import shell_without_heredoc_literals
from ci_gap_shell import (
    split_shell_command_segments as _split_shell_command_segments,
)
from ci_gap_shell import strip_inline_shell_comment as _strip_inline_shell_comment
from ci_gap_workflow_parser import (
    WorkflowCommand,
    _iter_workflow_run_commands,
    _locate_workflow_dirs,
)


@dataclass(frozen=True)
class GradleInvocation:
    workflow: pathlib.Path
    tokens: tuple[str, ...]


REQUIRED_GRADLE_TASKS = [
    ":app:testGrayDebugUnitTest",
    ":app:assertAndroidTestCountEqualsBaseline",
    ":app:lintGrayDebug",
    # Kotlin complexity gate (CODE_QUALITY_STANDARDS.md six thresholds) —
    ":app:detektGrayDebug",
    ":app:detektGrayDebugUnitTest",
    ":app:assembleGrayDebug",
    ":app:assembleInternalDebug",
    ":app:assembleGrayRelease",
    ":app:assembleInternalRelease",
    ":app:kspGrayDebugKotlin --rerun-tasks",
    # Runs on the path-filtered emulator lane (android-connected.yml) —
    ":app:connectedGrayDebugAndroidTest",
]

PLATFORM_WORKFLOW_PARTS = {"GitHub": ".github", "Gitea": ".gitea"}
REQUIRED_GRADLE_TASKS_BY_PLATFORM = {
    "GitHub": tuple(REQUIRED_GRADLE_TASKS),
    "Gitea": tuple(REQUIRED_GRADLE_TASKS),
}
PATH_SCOPED_RELEASE_TASKS = frozenset(
    {":app:assembleGrayRelease", ":app:assembleInternalRelease"}
)

def _is_line_continued(stripped_line: str) -> bool:
    return stripped_line.endswith("\\") or stripped_line.endswith("`")


def _line_without_continuation(stripped_line: str) -> str:
    return stripped_line[:-1].strip() if _is_line_continued(stripped_line) else stripped_line


def _is_gradle_executable(token: str) -> bool:
    normalized = token.strip("'\"").replace("\\", "/").lower()
    return normalized in {"gradlew", "./gradlew", ".//gradlew", ".\\gradlew.bat", "gradlew.bat", "./gradlew.bat"}


def _contains_gradle_executable(line: str) -> bool:
    return any(_is_gradle_executable(token) for token in _shell_tokens(line))


def _looks_like_gradle_arg_fragment(stripped_line: str) -> bool:
    return stripped_line.startswith(("-", ":"))


def _folded_command_text(text: str) -> str:
    paragraphs: list[list[str]] = [[]]
    for line in text.splitlines():
        if stripped := line.strip():
            paragraphs[-1].append(stripped)
        elif paragraphs[-1]:
            paragraphs.append([])
    return "\n".join(" ".join(paragraph) for paragraph in paragraphs if paragraph)


def _logical_command_lines(text: str, *, folded: bool) -> list[str]:
    if folded:
        text = _folded_command_text(text)
        folded = False
    text = shell_without_heredoc_literals(text)
    lines: list[str] = []
    buffer = ""
    buffer_has_gradle = False
    buffer_continues = False
    for raw_line in text.splitlines():
        stripped = _strip_inline_shell_comment(raw_line.strip()).strip()
        if not stripped:
            if buffer:
                lines.append(buffer)
                buffer = ""
                buffer_has_gradle = False
                buffer_continues = False
            continue
        piece = _line_without_continuation(stripped)
        should_join = buffer_continues or (folded and buffer_has_gradle and _looks_like_gradle_arg_fragment(stripped))
        if buffer and should_join:
            buffer = f"{buffer} {piece}"
        else:
            if buffer:
                lines.append(buffer)
            buffer = piece

        buffer_continues = _is_line_continued(stripped)
        buffer_has_gradle = _contains_gradle_executable(buffer)
        if not buffer_continues and not buffer_has_gradle:
            lines.append(buffer)
            buffer = ""

    if buffer:
        lines.append(buffer)
    return lines


def _gradle_invocation_from_segment(
    workflow: pathlib.Path,
    segment: str,
    *,
    require_direct: bool,
) -> GradleInvocation | None:
    if _is_output_command(segment.strip()):
        return None
    tokens = _shell_tokens(segment)
    executable_index = next((index for index, token in enumerate(tokens) if _is_gradle_executable(token)), None)
    if executable_index is None or (require_direct and executable_index != 0):
        return None
    return GradleInvocation(workflow, tokens[executable_index:])


def _gradle_invocations_from_line(
    workflow: pathlib.Path,
    line: str,
    *,
    require_failure_propagation: bool = True,
) -> list[GradleInvocation]:
    if require_failure_propagation and _has_unquoted_shell_separator(line):
        return []
    invocations = (
        _gradle_invocation_from_segment(
            workflow,
            segment,
            require_direct=require_failure_propagation,
        )
        for segment in _split_shell_command_segments(line)
    )
    return [invocation for invocation in invocations if invocation is not None]


def _gradle_line_propagates_failure(lines: list[str], index: int) -> bool:
    if index == len(lines) - 1:
        return True
    return _is_native_failure_propagation_guard(lines[index + 1])


def _iter_gradle_invocations(
    commands: list[WorkflowCommand],
    *,
    require_failure_propagation: bool = True,
) -> list[GradleInvocation]:
    invocations: list[GradleInvocation] = []
    for command in commands:
        lines = _logical_command_lines(command.text, folded=command.folded)
        if (
            require_failure_propagation
            and _contains_catch_block(lines)
            and not _catch_blocks_propagate_failure(lines)
        ):
            continue
        for index, line in enumerate(lines):
            parsed = _gradle_invocations_from_line(
                command.workflow,
                line,
                require_failure_propagation=require_failure_propagation,
            )
            if require_failure_propagation and not _gradle_line_propagates_failure(
                lines, index
            ):
                continue
            invocations.extend(parsed)
    return invocations


def _iter_executable_command_segments(commands: list[WorkflowCommand]) -> list[str]:
    segments: list[str] = []
    for command in commands:
        executable_lines = [
            line
            for line in _logical_command_lines(command.text, folded=command.folded)
            if not _is_output_command(line.strip())
        ]
        if len(executable_lines) != 1:
            if _contains_catch_block(executable_lines):
                continue
            for index, line in enumerate(executable_lines[:-1]):
                if (
                    not _has_unquoted_shell_separator(line)
                    and _is_native_failure_propagation_guard(executable_lines[index + 1])
                ):
                    segments.append(line)
            continue
        if not _has_unquoted_shell_separator(executable_lines[0]):
            segments.append(executable_lines[0])
    return segments


def _gradle_invocation_has_tokens(invocation: GradleInvocation, required: tuple[str, ...]) -> bool:
    token_set = set(invocation.tokens)
    return all(token in token_set for token in required)


def _missing_gradle_tasks(commands: list[WorkflowCommand]) -> list[str]:
    invocations = _iter_gradle_invocations(commands)
    return [
        task
        for task in REQUIRED_GRADLE_TASKS
        if not any(_gradle_invocation_has_tokens(invocation, tuple(task.split())) for invocation in invocations)
    ]


def _commands_for_platform(commands: list[WorkflowCommand], platform: str) -> list[WorkflowCommand]:
    return [command for command in commands if PLATFORM_WORKFLOW_PARTS[platform] in command.workflow.parts]


def _missing_gradle_tasks_by_platform(
    commands: list[WorkflowCommand],
    *,
    path_scoped_commands: list[WorkflowCommand] | None = None,
) -> list[str]:
    missing: list[str] = []
    scoped_commands = path_scoped_commands if path_scoped_commands is not None else commands
    for platform, required_tasks in REQUIRED_GRADLE_TASKS_BY_PLATFORM.items():
        platform_commands = _commands_for_platform(commands, platform)
        platform_scoped_commands = _commands_for_platform(scoped_commands, platform)
        for task in required_tasks:
            task_commands = (
                platform_scoped_commands
                if task in PATH_SCOPED_RELEASE_TASKS
                else platform_commands
            )
            allowed_scopes = (
                {"full", "android"}
                if task == ":app:connectedGrayDebugAndroidTest"
                else {"full"}
            )
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
    executable_segments = _iter_executable_command_segments(commands)
    return [
        required.label
        for required in REQUIRED_CI_INVOCATIONS
        if not any(required.matches(segment) for segment in executable_segments)
    ]


def _missing_ci_invocations_by_platform(commands: list[WorkflowCommand]) -> list[str]:
    missing: list[str] = []
    for platform in PLATFORM_WORKFLOW_PARTS:
        platform_commands = [
            command
            for command in _commands_for_platform(commands, platform)
            if command.protection_scope == "full"
        ]
        for label in _missing_ci_invocations(platform_commands):
            missing.append(f"{platform}: {label}")
        executable_segments = _iter_executable_command_segments(platform_commands)
        for required in REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform]:
            if not any(required.matches(segment) for segment in executable_segments):
                missing.append(f"{platform}: {required.label}")
    return missing


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


def main() -> int:
    workflow_dirs = _locate_workflow_dirs()
    if not workflow_dirs:
        print("CI gap audit: FAIL - no Actions workflow directory found")
        return 1

    workflow_labels = ", ".join(str(path) for path in workflow_dirs)
    if not any(".github" in path.parts and "workflows" in path.parts for path in workflow_dirs):
        print("CI gap audit: FAIL - .github/workflows/ directory not found")
        return 1

    commands = _iter_workflow_run_commands(workflow_dirs, protected_only=True)
    path_scoped_commands = _iter_workflow_run_commands(workflow_dirs)
    missing: list[str] = []
    for task in _missing_gradle_tasks_by_platform(
        commands,
        path_scoped_commands=path_scoped_commands,
    ):
        missing.append(f"gradle task: {task}")
    for invocation in _missing_ci_invocations_by_platform(commands):
        missing.append(f"ci invocation: {invocation}")
    for violation in _github_ci_release_apk_policy_violations(path_scoped_commands):
        missing.append(f"ci policy: {violation}")
    for violation in _gitea_ci_release_apk_policy_violations(path_scoped_commands):
        missing.append(f"ci policy: {violation}")
    for violation in _github_external_uses_pin_violations(workflow_dirs):
        missing.append(f"ci policy: {violation}")
    for violation in release_apk_scope_policy_violations(
        {command.workflow for command in path_scoped_commands}
    ):
        missing.append(f"ci policy: {violation}")

    if missing:
        print("=== CI gap audit: FAIL ===")
        for entry in missing:
            print(f"  missing from required platform workflow set: {entry}")
        return 1

    print(
        f"=== CI gap audit: OK ({len(REQUIRED_GRADLE_TASKS)} gradle tasks + "
        f"{len(REQUIRED_CI_INVOCATIONS)} backend invocations per platform + dual-platform release APK "
        f"and external uses SHA-pin policies verified independently across "
        f"Actions workflows: {workflow_labels}) ==="
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
