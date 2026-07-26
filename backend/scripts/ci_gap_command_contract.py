"""Shell-command parsing shared by the CI gap audit and its contract tests."""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from hashlib import sha256

from ci_gap_powershell import (
    is_native_failure_propagation_guard as _is_native_failure_propagation_guard,
)
from ci_gap_powershell import looks_like_powershell as _looks_like_powershell
from ci_gap_powershell import (
    powershell_ast_propagates_failure as _powershell_ast_propagates_failure,
)
from ci_gap_shell import has_unquoted_shell_separator as _has_unquoted_shell_separator
from ci_gap_shell import is_output_command as _is_output_command
from ci_gap_shell import shell_tokens as _shell_tokens
from ci_gap_shell import shell_without_heredoc_literals
from ci_gap_shell import split_shell_command_segments as _split_shell_command_segments
from ci_gap_shell import strip_inline_shell_comment as _strip_inline_shell_comment
from ci_gap_workflow_parser import WorkflowCommand


@dataclass(frozen=True)
class GradleInvocation:
    workflow: pathlib.Path
    tokens: tuple[str, ...]


REQUIRED_GRADLE_TASKS = [
    ":app:testGrayDebugUnitTest",
    ":app:assertAndroidTestCountEqualsBaseline",
    ":app:lintGrayDebug",
    ":app:detektGrayDebug",
    ":app:detektGrayDebugUnitTest",
    ":app:assembleGrayDebug",
    ":app:assembleInternalDebug",
    ":app:assembleGrayRelease",
    ":app:assembleInternalRelease",
    ":app:kspGrayDebugKotlin --rerun-tasks",
    ":app:connectedGrayDebugAndroidTest",
]
_GRADLE_NO_ACTION_OPTIONS = {"-m", "--dry-run", "--task-graph"}
_GRADLE_EXCLUDE_OPTIONS = {"-x", "--exclude-task"}
_TIMEOUT_OPTIONS_WITH_VALUE = {"-k", "--kill-after", "-s", "--signal"}
_TIMEOUT_FLAG_OPTIONS = {"--foreground", "--preserve-status", "--verbose"}
_TIMEOUT_DURATION = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
_TIMEOUT_SIGNAL_NAMES = {
    "ABRT",
    "ALRM",
    "BUS",
    "CHLD",
    "CONT",
    "FPE",
    "HUP",
    "ILL",
    "INT",
    "IO",
    "KILL",
    "PIPE",
    "PROF",
    "PWR",
    "QUIT",
    "SEGV",
    "STOP",
    "SYS",
    "TERM",
    "TRAP",
    "TSTP",
    "TTIN",
    "TTOU",
    "URG",
    "USR1",
    "USR2",
    "VTALRM",
    "WINCH",
    "XCPU",
    "XFSZ",
}


def _is_line_continued(stripped_line: str) -> bool:
    return stripped_line.endswith("\\") or stripped_line.endswith("`")


def _line_without_continuation(stripped_line: str) -> str:
    return stripped_line[:-1].strip() if _is_line_continued(stripped_line) else stripped_line


def _is_gradle_executable(token: str) -> bool:
    normalized = token.strip("'\"").replace("\\", "/").lower()
    return normalized in {
        "gradlew",
        "./gradlew",
        ".//gradlew",
        ".\\gradlew.bat",
        "gradlew.bat",
        "./gradlew.bat",
    }


def _contains_gradle_executable(line: str) -> bool:
    return any(_is_gradle_executable(token) for token in _shell_tokens(line))


def _valid_timeout_option_value(option: str, value: str) -> bool:
    if option in {"-k", "--kill-after"}:
        return _TIMEOUT_DURATION.fullmatch(value) is not None
    if option not in {"-s", "--signal"}:
        return False
    if value.isdecimal():
        return 1 <= int(value) <= 64
    normalized = value.upper().removeprefix("SIG")
    return normalized in _TIMEOUT_SIGNAL_NAMES


def _timeout_wraps_direct_gradle(
    tokens: tuple[str, ...],
    executable_index: int,
) -> bool:
    if not tokens or tokens[0].strip("'\"").lower() != "timeout":
        return False
    index = 1
    while index < executable_index:
        token = tokens[index].strip("'\"")
        option_name, separator, option_value = token.partition("=")
        if (
            separator
            and option_name in _TIMEOUT_OPTIONS_WITH_VALUE
            and _valid_timeout_option_value(option_name, option_value)
        ):
            index += 1
            continue
        if separator:
            return False
        if token in _TIMEOUT_OPTIONS_WITH_VALUE:
            if (
                index + 1 >= executable_index
                or not _valid_timeout_option_value(
                    token,
                    tokens[index + 1].strip("'\""),
                )
            ):
                return False
            index += 2
            continue
        if token in _TIMEOUT_FLAG_OPTIONS:
            index += 1
            continue
        break
    return (
        index + 1 == executable_index
        and index < len(tokens)
        and _TIMEOUT_DURATION.fullmatch(tokens[index].strip("'\"")) is not None
    )


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
        should_join = buffer_continues or (
            folded and buffer_has_gradle and _looks_like_gradle_arg_fragment(stripped)
        )
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
    executable_index = next(
        (index for index, token in enumerate(tokens) if _is_gradle_executable(token)),
        None,
    )
    if executable_index is None:
        return None
    if (
        require_direct
        and executable_index != 0
        and not _timeout_wraps_direct_gradle(
            tokens,
            executable_index,
        )
    ):
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


def _command_passes_powershell_ast(command: WorkflowCommand) -> bool:
    text_digest = sha256(command.text.encode("utf-8")).hexdigest()
    if command.powershell_ast_digest == text_digest:
        return True
    if not _looks_like_powershell(shell=command.shell, command=command.text):
        return True
    return _powershell_ast_propagates_failure(command.text)


def _iter_gradle_invocations(
    commands: list[WorkflowCommand],
    *,
    require_failure_propagation: bool = True,
) -> list[GradleInvocation]:
    invocations: list[GradleInvocation] = []
    for command in commands:
        if require_failure_propagation and not _command_passes_powershell_ast(command):
            continue
        lines = _logical_command_lines(command.text, folded=command.folded)
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
        if not _command_passes_powershell_ast(command):
            continue
        executable_lines = [
            line
            for line in _logical_command_lines(command.text, folded=command.folded)
            if not _is_output_command(line.strip())
        ]
        if len(executable_lines) != 1:
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


def _gradle_invocation_has_tokens(
    invocation: GradleInvocation,
    required: tuple[str, ...],
) -> bool:
    if any(token in _GRADLE_NO_ACTION_OPTIONS for token in invocation.tokens) or (
        _excluded_gradle_tasks(invocation.tokens)
    ):
        return False
    token_set = set(invocation.tokens)
    return all(token in token_set for token in required)


def _excluded_gradle_tasks(tokens: tuple[str, ...]) -> tuple[str, ...]:
    excluded: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _GRADLE_EXCLUDE_OPTIONS:
            if index + 1 < len(tokens):
                excluded.append(tokens[index + 1])
                index += 1
        elif token.startswith(("--exclude-task=", "-x=")):
            excluded.append(token.partition("=")[2])
        elif token.startswith("-x") and len(token) > 2:
            excluded.append(token[2:])
        index += 1
    return tuple(task for task in excluded if task)


def _missing_gradle_tasks(commands: list[WorkflowCommand]) -> list[str]:
    invocations = _iter_gradle_invocations(commands)
    return [
        task
        for task in REQUIRED_GRADLE_TASKS
        if not any(
            _gradle_invocation_has_tokens(invocation, tuple(task.split()))
            for invocation in invocations
        )
    ]
