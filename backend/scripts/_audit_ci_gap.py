"""Read-only audit: CI invokes every pinned gradle task / pytest lane."""

from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class RequiredCommand:
    label: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class WorkflowCommand:
    workflow: pathlib.Path
    text: str
    folded: bool = False


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

REQUIRED_CI_INVOCATIONS = [
    RequiredCommand(
        "release audit aggregator",
        re.compile(r"\bpython(?:\.exe)?\s+scripts[\\/]+release_audit\.py\b"),
    ),
    RequiredCommand(
        "pytest full-suite lane",
        re.compile(r"\bpython(?:\.exe)?\s+-m\s+pytest\b[^\n]*-p no:cacheprovider"),
    ),
    RequiredCommand(
        "end-to-end smoke",
        re.compile(r"\bpython(?:\.exe)?\s+scripts[\\/]+smoke_test\.py\b"),
    ),
    RequiredCommand(
        # in the Gitea move — pinned so it cannot vanish again.
        "backup/restore drill",
        re.compile(r"\bpython(?:\.exe)?\s+scripts[\\/]+postgres_backup_drill\.py\b"),
    ),
    RequiredCommand(
        "API contract check",
        re.compile(r"\bpython(?:\.exe)?\s+scripts[\\/]+check_api_contract\.py\b"),
    ),
    RequiredCommand(
        # ``app scripts tests`` anchors the backend target set — the desktop
        "backend ruff lint",
        re.compile(r"\bruff(?:\.exe)?\s+check\s+app\s+scripts\s+tests\b"),
    ),
    RequiredCommand(
        "backend compileall",
        re.compile(r"\bpython(?:\.exe)?\s+-m\s+compileall\s+app\s+scripts\s+tests\b"),
    ),
    # Desktop-manager job pins — previously the whole job could be deleted
    RequiredCommand(
        "desktop compileall",
        re.compile(r"\bpython(?:\.exe)?\s+-m\s+compileall\s+backend_manager\s+tests\b"),
    ),
    RequiredCommand(
        "desktop ruff lint",
        re.compile(r"\bruff(?:\.exe)?\s+check\s+backend_manager\s+tests\b"),
    ),
    RequiredCommand(
        "desktop pytest",
        re.compile(r"\bpython(?:\.exe)?\s+-m\s+pytest\s+-q\s*$", re.MULTILINE),
    ),
]

OUTPUT_COMMAND_PREFIXES = ("echo", "printf", "write-host", "write-output")


def _locate_workflow_dirs() -> list[pathlib.Path]:
    candidates = [
        pathlib.Path("../.github/workflows"),
        pathlib.Path("../.gitea/workflows"),
        pathlib.Path(".github/workflows"),
        pathlib.Path(".gitea/workflows"),
    ]
    found: list[pathlib.Path] = []
    for candidate in candidates:
        if candidate.is_dir():
            resolved = candidate.resolve()
            if resolved not in found:
                found.append(resolved)
    return found


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _command_key(stripped_line: str) -> str | None:
    stripped = stripped_line
    if stripped.startswith("- "):
        stripped = stripped[2:].lstrip()
    if stripped.startswith("run:"):
        return "run:"
    if stripped.startswith("script:"):
        return "script:"
    return None


def _command_value(stripped_line: str, key: str) -> str:
    stripped = stripped_line
    if stripped.startswith("- "):
        stripped = stripped[2:].lstrip()
    return stripped.removeprefix(key).strip()


def _false_if_block_parent_indent(line: str) -> int | None:
    stripped = line.lstrip()
    if stripped.startswith("- "):
        stripped = stripped[2:].lstrip()
    if not stripped.startswith("if:"):
        return None
    value = stripped.removeprefix("if:").strip().strip("'\"")
    normalized = re.sub(r"\s+", " ", value).lower()
    if normalized in {"false", "${{ false }}", "${{false}}"}:
        return max(0, _line_indent(line) - 2)
    return None


def _read_yaml_command_block(
    lines: list[str], *, start_index: int, parent_indent: int
) -> tuple[str, int]:
    block: list[str] = []
    index = start_index
    while index < len(lines):
        child = lines[index]
        if child.strip() and _line_indent(child) <= parent_indent:
            break
        block.append(child)
        index += 1
    return "\n".join(block), index


def _strip_comment_lines(text: str) -> str:
    """Drop ``#``-commented lines inside a run body.

    A required command that someone disabled by commenting it out inside a
    multi-line ``run: |`` block must not satisfy the gate.
    """
    kept = [
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    return "\n".join(kept)


def _strip_inline_shell_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if char == "\\" and not in_single:
            escaped = not escaped
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or line[index - 1].isspace() or line[index - 1] in ";&|()")
        ):
            return line[:index].rstrip()
        escaped = False
    return line


def _prune_disabled_stack(disabled_parent_indents: list[int], line: str) -> None:
    if not line.strip():
        return
    indent = _line_indent(line)
    while disabled_parent_indents and indent <= disabled_parent_indents[-1]:
        disabled_parent_indents.pop()


def _workflow_dir_list(workflow_dirs: pathlib.Path | list[pathlib.Path]) -> list[pathlib.Path]:
    if isinstance(workflow_dirs, pathlib.Path):
        return [workflow_dirs]
    return workflow_dirs


def _iter_workflow_run_commands(
    workflow_dirs: pathlib.Path | list[pathlib.Path],
) -> list[WorkflowCommand]:
    commands: list[WorkflowCommand] = []
    for workflow_dir in _workflow_dir_list(workflow_dirs):
        for path in sorted(workflow_dir.glob("*.yml")):
            lines = path.read_text(encoding="utf-8").splitlines()
            index = 0
            disabled_parent_indents: list[int] = []
            while index < len(lines):
                line = lines[index]
                indent = _line_indent(line)
                # Blank lines have indent 0 but carry no structure — letting them
                # pop the stack would un-mute an ``if: false`` step whose ``run:``
                # sits after a blank line, so a disabled step could satisfy pins.
                _prune_disabled_stack(disabled_parent_indents, line)
                disabled_parent_indent = _false_if_block_parent_indent(line)
                if disabled_parent_indent is not None:
                    disabled_parent_indents.append(disabled_parent_indent)
                    index += 1
                    continue
                stripped = line.lstrip()
                key = _command_key(stripped)
                if key is None:
                    index += 1
                    continue
                if disabled_parent_indents:
                    index += 1
                    continue

                value = _command_value(stripped, key)
                if value in {"|", ">"}:
                    text, index = _read_yaml_command_block(
                        lines,
                        start_index=index + 1,
                        parent_indent=indent,
                    )
                    text = text if value == ">" else _strip_comment_lines(text)
                    commands.append(WorkflowCommand(path, text, folded=value == ">"))
                    continue

                commands.append(WorkflowCommand(path, _strip_comment_lines(value)))
                index += 1
    return commands


def _is_output_command(stripped_line: str) -> bool:
    first_token = stripped_line.split(maxsplit=1)[0].lower() if stripped_line else ""
    return first_token in OUTPUT_COMMAND_PREFIXES


def _is_line_continued(stripped_line: str) -> bool:
    return stripped_line.endswith("\\") or stripped_line.endswith("`")


def _line_without_continuation(stripped_line: str) -> str:
    return stripped_line[:-1].strip() if _is_line_continued(stripped_line) else stripped_line


def _shell_tokens(line: str) -> tuple[str, ...]:
    return tuple(token.strip("'\"") for token in re.findall(r"""(?:"[^"]*"|'[^']*'|\S+)""", line))


def _quote_state_after_char(char: str, *, in_single: bool, in_double: bool, escaped: bool) -> tuple[bool, bool]:
    if char == "'" and not in_double and not escaped:
        return (not in_single, in_double)
    if char == '"' and not in_single and not escaped:
        return (in_single, not in_double)
    return (in_single, in_double)


def _is_unquoted_shell_separator(char: str, *, in_single: bool, in_double: bool) -> bool:
    return not in_single and not in_double and char in ";&|"


def _split_shell_command_segments(line: str) -> list[str]:
    segments: list[str] = []
    start = 0
    in_single = False
    in_double = False
    escaped = False
    skip_next = False
    for index, char in enumerate(line):
        if skip_next:
            skip_next = False
            continue
        if char == "\\" and not in_single:
            escaped = not escaped
            continue
        in_single, in_double = _quote_state_after_char(
            char,
            in_single=in_single,
            in_double=in_double,
            escaped=escaped,
        )
        if _is_unquoted_shell_separator(char, in_single=in_single, in_double=in_double):
            segments.append(line[start:index].strip())
            skip_next = index + 1 < len(line) and line[index + 1] == char
            start = index + 2 if skip_next else index + 1
        escaped = False
    segments.append(line[start:].strip())
    return [segment for segment in segments if segment]


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
    lines: list[str] = []
    buffer = ""
    buffer_has_gradle = False
    buffer_continues = False
    heredoc_end: str | None = None
    for raw_line in text.splitlines():
        if heredoc_end is not None:
            if raw_line.strip() == heredoc_end:
                heredoc_end = None
            continue
        stripped = _strip_inline_shell_comment(raw_line.strip()).strip()
        heredoc_match = re.search(r"(?<!<)<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|([^ \t;&|()<>]+))", stripped)
        if heredoc_match:
            heredoc_end = next(group for group in heredoc_match.groups() if group is not None)
            stripped = f"{stripped[: heredoc_match.start()].rstrip()} {stripped[heredoc_match.end() :].lstrip()}".strip()
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


def _gradle_invocation_from_segment(workflow: pathlib.Path, segment: str) -> GradleInvocation | None:
    if _is_output_command(segment.strip()):
        return None
    tokens = _shell_tokens(segment)
    executable_index = next((index for index, token in enumerate(tokens) if _is_gradle_executable(token)), None)
    if executable_index is None:
        return None
    return GradleInvocation(workflow, tokens[executable_index:])


def _gradle_invocations_from_line(workflow: pathlib.Path, line: str) -> list[GradleInvocation]:
    invocations = (_gradle_invocation_from_segment(workflow, segment) for segment in _split_shell_command_segments(line))
    return [invocation for invocation in invocations if invocation is not None]


def _iter_gradle_invocations(commands: list[WorkflowCommand]) -> list[GradleInvocation]:
    invocations: list[GradleInvocation] = []
    for command in commands:
        for line in _logical_command_lines(command.text, folded=command.folded):
            invocations.extend(_gradle_invocations_from_line(command.workflow, line))
    return invocations


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


def _missing_ci_invocations(commands: list[WorkflowCommand]) -> list[str]:
    missing: list[str] = []
    for required in REQUIRED_CI_INVOCATIONS:
        if not any(required.pattern.search(command.text) for command in commands):
            missing.append(required.label)
    return missing


def _is_github_workflow(path: pathlib.Path) -> bool:
    return ".github" in path.parts and "workflows" in path.parts


def _has_max_workers_one(tokens: tuple[str, ...]) -> bool:
    for index, token in enumerate(tokens):
        if token == "--max-workers=1":
            return True
        if token == "--max-workers" and index + 1 < len(tokens) and tokens[index + 1] == "1":
            return True
    return False


def _is_release_apk_invocation(invocation: GradleInvocation) -> bool:
    return _gradle_invocation_has_tokens(
        invocation,
        (":app:assembleGrayRelease", ":app:assembleInternalRelease"),
    )


def _github_ci_release_apk_policy_violations(commands: list[WorkflowCommand]) -> list[str]:
    github_gradle_invocations = [
        invocation for invocation in _iter_gradle_invocations(commands) if _is_github_workflow(invocation.workflow)
    ]
    violations: list[str] = []
    if not any(_is_release_apk_invocation(invocation) and _has_max_workers_one(invocation.tokens) for invocation in github_gradle_invocations):
        violations.append(
            "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
        )
    if any("--stop" in invocation.tokens for invocation in github_gradle_invocations):
        violations.append("GitHub CI must not call gradlew --stop during Android lanes")
    return violations


def main() -> int:
    workflow_dirs = _locate_workflow_dirs()
    if not workflow_dirs:
        print("CI gap audit: FAIL - no Actions workflow directory found")
        return 1

    workflow_labels = ", ".join(str(path) for path in workflow_dirs)
    if not any(".github" in path.parts and "workflows" in path.parts for path in workflow_dirs):
        print("CI gap audit: FAIL - .github/workflows/ directory not found")
        return 1

    commands = _iter_workflow_run_commands(workflow_dirs)
    missing: list[str] = []
    for task in _missing_gradle_tasks(commands):
        missing.append(f"gradle task: {task}")
    for invocation in _missing_ci_invocations(commands):
        missing.append(f"ci invocation: {invocation}")
    for violation in _github_ci_release_apk_policy_violations(commands):
        missing.append(f"ci policy: {violation}")

    if missing:
        print("=== CI gap audit: FAIL ===")
        for entry in missing:
            print(f"  missing across Actions workflows: {entry}")
        return 1

    print(
        f"=== CI gap audit: OK ({len(REQUIRED_GRADLE_TASKS)} gradle tasks + "
        f"{len(REQUIRED_CI_INVOCATIONS)} backend invocations + GitHub release APK "
        f"policy verified across all "
        f"Actions workflows: {workflow_labels}) ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
