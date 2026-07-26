"""Resolve checked-in shell entrypoints referenced by CI workflow steps."""

from __future__ import annotations

import pathlib
import re
import shlex

from ci_gap_shell import shell_tokens, split_shell_command_segments, strip_inline_shell_comment

_LOCAL_SHELL_LAUNCHERS = {
    "/bin/bash",
    "/bin/sh",
    "/usr/bin/bash",
    "/usr/bin/sh",
}
_SHELL_FUNCTION_START = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)\s*\{\s*$"
)
_SHELL_FUNCTION_END = re.compile(r"^}\s*;?\s*$")
_SHELL_CONTROL_PREFIXES = {"!", "do", "elif", "else", "if", "then", "until", "while"}
_SHELL_PREMATURE_TERMINATORS = {".", "eval", "exec", "exit", "return", "source"}


def _repository_root(path: pathlib.Path) -> pathlib.Path | None:
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name in {".github", ".gitea"}:
            return parent.parent
    return None


def _step_working_directory(raw_step: dict[object, object]) -> str:
    direct = raw_step.get("working-directory")
    if isinstance(direct, str):
        return direct
    inputs = raw_step.get("with")
    if isinstance(inputs, dict):
        nested = inputs.get("working-directory")
        if isinstance(nested, str):
            return nested
    return ""


def _is_gradle_token(token: str) -> bool:
    return token.strip("'\"").lower() == "./gradlew"


def _segment_command(segment: str) -> str:
    tokens = list(shell_tokens(segment))
    while tokens:
        candidate = tokens.pop(0).strip(";&|(){}")
        if not candidate or candidate in _SHELL_CONTROL_PREFIXES:
            continue
        return candidate
    return ""


def _reaches_top_level_gradle_without_premature_termination(script: str) -> bool:
    in_function = False
    for raw_line in script.splitlines():
        line = strip_inline_shell_comment(raw_line.strip()).strip()
        if not line:
            continue
        if in_function:
            if _SHELL_FUNCTION_END.fullmatch(line):
                in_function = False
            continue
        if _SHELL_FUNCTION_START.fullmatch(line):
            in_function = True
            continue
        if any(_is_gradle_token(token) for token in shell_tokens(line)):
            return True
        for segment in split_shell_command_segments(line):
            if _segment_command(segment) in _SHELL_PREMATURE_TERMINATORS:
                return False
    return False


def local_shell_script_text(
    path: pathlib.Path,
    raw_step: dict[object, object],
    command: str,
) -> str | None:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if (
        len(tokens) != 2
        or tokens[0] not in _LOCAL_SHELL_LAUNCHERS
        or tokens[1].startswith("-")
    ):
        return None

    repository_root = _repository_root(path)
    if repository_root is None:
        return None
    working_directory = pathlib.Path(_step_working_directory(raw_step))
    if working_directory.is_absolute():
        return None
    resolved_working_directory = (repository_root / working_directory).resolve()
    if not resolved_working_directory.is_relative_to(repository_root):
        return None

    script_path = pathlib.Path(tokens[1])
    if script_path.is_absolute() or script_path.suffix.lower() != ".sh":
        return None
    resolved_script = (resolved_working_directory / script_path).resolve()
    if (
        not resolved_script.is_relative_to(repository_root)
        or not resolved_script.is_file()
    ):
        return None
    try:
        script = resolved_script.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if not _reaches_top_level_gradle_without_premature_termination(script):
        return None
    return script
