"""Read-only audit: CI invokes every gradle task / pytest lane we expect.

This lane scans actual Gitea Actions ``run:`` command bodies (the live CI,
``.gitea/workflows/``) instead of global workflow text. Comments and prose
cannot satisfy the gate.
"""

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


# Gradle tasks that CI must invoke. Update when adding a new test / lint /
# build lane that should not silently regress.
# ``:app:connectedGrayDebugAndroidTest`` is intentionally absent: the live
# Gitea CI has no emulator lane (the GitHub-era android-connected-test.yml
# died with the move), so requiring it would only recreate the vacuous green
# this lane had while it still scanned the dead ``.github/`` workflows.
# Re-add it together with the actual CI lane once the instrumented gap is
# resolved.
REQUIRED_GRADLE_TASKS = [
    ":app:testGrayDebugUnitTest",
    ":app:assertAndroidTestCountEqualsBaseline",
    ":app:lintGrayDebug",
    ":app:assembleGrayDebug",
    ":app:assembleInternalDebug",
    ":app:assembleGrayRelease",
    ":app:assembleInternalRelease",
]

# Backend invocations expected in CI. These match actual run-command bodies,
# not global workflow text, so comments cannot satisfy the gate.
REQUIRED_CI_INVOCATIONS = [
    RequiredCommand(
        "release audit aggregator",
        re.compile(r"\bpython(?:\.exe)?\s+scripts[\\/]+release_audit\.py\b"),
    ),
    RequiredCommand(
        # Anchored on the backend suite's signature flag: the desktop job also
        # runs ``python -m pytest``, so a bare pytest matcher would stay green
        # with the backend suite gone.
        "pytest full-suite lane",
        re.compile(r"\bpython(?:\.exe)?\s+-m\s+pytest\b[^\n]*-p no:cacheprovider"),
    ),
    RequiredCommand(
        "end-to-end smoke",
        re.compile(r"\bpython(?:\.exe)?\s+scripts[\\/]+smoke_test\.py\b"),
    ),
    RequiredCommand(
        # ENGINEERING_RULES section 6: a backup without a restore drill is no
        # backup. The drill lived on the GitHub-era PG lane and silently died
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
        # job lints ``backend_manager tests`` and must not satisfy this.
        "backend ruff lint",
        re.compile(r"\bruff(?:\.exe)?\s+check\s+app\s+scripts\s+tests\b"),
    ),
    RequiredCommand(
        "backend compileall",
        re.compile(r"\bpython(?:\.exe)?\s+-m\s+compileall\s+app\s+scripts\s+tests\b"),
    ),
]


def _locate_workflow_dir() -> pathlib.Path | None:
    candidates = [
        pathlib.Path("../.gitea/workflows"),
        pathlib.Path(".gitea/workflows"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


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


def _iter_workflow_run_commands(workflow_dir: pathlib.Path) -> list[WorkflowCommand]:
    commands: list[WorkflowCommand] = []
    for path in sorted(workflow_dir.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        index = 0
        disabled_parent_indents: list[int] = []
        while index < len(lines):
            line = lines[index]
            indent = _line_indent(line)
            while disabled_parent_indents and indent <= disabled_parent_indents[-1]:
                disabled_parent_indents.pop()
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
                commands.append(WorkflowCommand(path, _strip_comment_lines(text)))
                continue

            commands.append(WorkflowCommand(path, _strip_comment_lines(value)))
            index += 1
    return commands


def _missing_gradle_tasks(commands: list[WorkflowCommand]) -> list[str]:
    command_text = "\n".join(command.text for command in commands)
    return [task for task in REQUIRED_GRADLE_TASKS if task not in command_text]


def _missing_ci_invocations(commands: list[WorkflowCommand]) -> list[str]:
    missing: list[str] = []
    for required in REQUIRED_CI_INVOCATIONS:
        if not any(required.pattern.search(command.text) for command in commands):
            missing.append(required.label)
    return missing


def main() -> int:
    workflow_dir = _locate_workflow_dir()
    if workflow_dir is None:
        print("CI gap audit: FAIL - .gitea/workflows/ directory not found")
        return 1

    commands = _iter_workflow_run_commands(workflow_dir)
    missing: list[str] = []
    for task in _missing_gradle_tasks(commands):
        missing.append(f"gradle task: {task}")
    for invocation in _missing_ci_invocations(commands):
        missing.append(f"ci invocation: {invocation}")

    if missing:
        print("=== CI gap audit: FAIL ===")
        for entry in missing:
            print(f"  missing across .gitea/workflows/*.yml: {entry}")
        return 1

    print(
        f"=== CI gap audit: OK ({len(REQUIRED_GRADLE_TASKS)} gradle tasks + "
        f"{len(REQUIRED_CI_INVOCATIONS)} backend invocations verified across all "
        f".gitea/workflows/*.yml) ==="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
