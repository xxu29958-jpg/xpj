"""Require a real Desktop dependency audit in each selected CI provider."""

from __future__ import annotations

import pathlib
import re
import sys

from ci_audit_provider import PLATFORM_WORKFLOW_PARTS, selected_ci_platforms
from ci_gap_command_contract import (
    _is_output_command,
    _logical_command_lines,
    _shell_tokens,
    _split_shell_command_segments,
)
from ci_gap_workflow_parser import _iter_workflow_run_commands, _locate_workflow_dirs

_DESKTOP_REQUIREMENT = re.compile(r"^\.\.[\\/]desktop[\\/]requirements\.txt$")


def _has_desktop_requirement(tokens: tuple[str, ...]) -> bool:
    for index, token in enumerate(tokens):
        if token in {"-r", "--requirement"}:
            if index + 1 < len(tokens) and _DESKTOP_REQUIREMENT.match(tokens[index + 1]):
                return True
        elif token.startswith("--requirement="):
            _, requirement = token.split("=", 1)
            if _DESKTOP_REQUIREMENT.match(requirement):
                return True
    return False


def _is_live_desktop_audit(segment: str) -> bool:
    stripped = segment.strip()
    if _is_output_command(stripped):
        return False
    tokens = _shell_tokens(stripped)
    if not tokens:
        return False
    executable = re.split(r"[\\/]", tokens[0])[-1].lower()
    module_form = executable in {"python", "python.exe"} and tokens[1:3] == ("-m", "pip_audit")
    direct_form = executable in {"pip-audit", "pip-audit.exe"}
    return (module_form or direct_form) and _has_desktop_requirement(tokens)


def missing_provider_audits(
    workflow_dirs: list[pathlib.Path],
    *,
    platforms: tuple[str, ...] = tuple(PLATFORM_WORKFLOW_PARTS),
) -> list[str]:
    commands = _iter_workflow_run_commands(workflow_dirs)
    missing: list[str] = []
    for platform in platforms:
        provider = PLATFORM_WORKFLOW_PARTS[platform]
        found = any(
            _is_live_desktop_audit(segment)
            for command in commands
            if provider in command.workflow.parts
            for line in _logical_command_lines(command.text, folded=command.folded)
            for segment in _split_shell_command_segments(line)
        )
        if not found:
            missing.append(provider)
    return missing


def main() -> int:
    try:
        platforms = selected_ci_platforms()
    except ValueError as exc:
        print(f"Desktop dependency CI audit: FAIL - {exc}")
        return 1
    missing = missing_provider_audits(_locate_workflow_dirs(), platforms=platforms)
    if missing:
        print(f"Desktop dependency CI audit: FAIL - missing live pip-audit in {', '.join(missing)}")
        return 1
    print("Desktop dependency CI audit: PASS - selected provider audits desktop/requirements.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
