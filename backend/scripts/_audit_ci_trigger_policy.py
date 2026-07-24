"""Read-only audit: cloud and fallback CI trigger policy stays intentional."""

from __future__ import annotations

import pathlib
import re
import sys

from ci_audit_provider import selected_ci_platforms
from ci_gap_trigger_scope import ANDROID_PROTECTED_PATHS

ROOT = pathlib.Path(__file__).resolve().parents[2]
GITHUB_WORKFLOWS = ROOT / ".github" / "workflows"
GITEA_WORKFLOWS = ROOT / ".gitea" / "workflows"

GITHUB_MAIN_ONLY = ("main",)
GITEA_WORK_BRANCHES = ("main", "feat/**", "fix/**", "perf/**", "refactor/**", "codex/**")
CODEQL_WEEKLY_CRON = "37 3 * * 1"
GITHUB_CONNECTED_PATHS = (
    *ANDROID_PROTECTED_PATHS,
    ".github/workflows/android-connected-test.yml",
)
GITEA_CONNECTED_PATHS = (
    *ANDROID_PROTECTED_PATHS,
    ".gitea/workflows/android-connected.yml",
)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _read_lines(path: pathlib.Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _event_block(path: pathlib.Path, event_name: str) -> list[str]:
    lines = _read_lines(path)
    start_index: int | None = None
    event_indent: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == f"{event_name}:":
            start_index = index
            event_indent = _indent(line)
            break
    if start_index is None or event_indent is None:
        return []

    block: list[str] = []
    for line in lines[start_index + 1 :]:
        if line.strip() and _indent(line) <= event_indent:
            break
        block.append(line)
    return block


def _event_present(path: pathlib.Path, event_name: str) -> bool:
    return any(line.strip() == f"{event_name}:" for line in _read_lines(path))


def _sequence_values(block: list[str], key: str) -> list[str]:
    start_index: int | None = None
    key_indent: int | None = None
    for index, line in enumerate(block):
        if line.strip() == f"{key}:":
            start_index = index
            key_indent = _indent(line)
            break
    if start_index is None or key_indent is None:
        return []

    values: list[str] = []
    for line in block[start_index + 1 :]:
        if line.strip() and _indent(line) <= key_indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            values.append(stripped[2:].strip().strip('"').strip("'"))
    return values


def _branches(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    return tuple(_sequence_values(_event_block(path, event_name), "branches"))


def _paths(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    return tuple(_sequence_values(_event_block(path, event_name), "paths"))


def _schedule_crons(path: pathlib.Path) -> tuple[str, ...]:
    block = _event_block(path, "schedule")
    crons: list[str] = []
    cron_rx = re.compile(r"""-\s+cron:\s*["']?([^"']+)["']?""")
    for line in block:
        match = cron_rx.search(line.strip())
        if match:
            crons.append(match.group(1))
    return tuple(crons)


def _expect_exact(label: str, actual: tuple[str, ...], expected: tuple[str, ...], failures: list[str]) -> None:
    if actual != expected:
        failures.append(f"{label}: expected {list(expected)}, got {list(actual)}")


def _audit_github_main_pr_policy(failures: list[str]) -> None:
    for workflow_name in ("ci.yml", "android-connected-test.yml", "codeql.yml"):
        path = GITHUB_WORKFLOWS / workflow_name
        _expect_exact(f"{workflow_name} push branches", _branches(path, "push"), GITHUB_MAIN_ONLY, failures)
        _expect_exact(
            f"{workflow_name} pull_request branches",
            _branches(path, "pull_request"),
            GITHUB_MAIN_ONLY,
            failures,
        )
        if not _event_present(path, "workflow_dispatch"):
            failures.append(f"{workflow_name}: missing workflow_dispatch trigger")

    connected = GITHUB_WORKFLOWS / "android-connected-test.yml"
    push_paths = _paths(connected, "push")
    pr_paths = _paths(connected, "pull_request")
    _expect_exact("android-connected-test.yml push paths", push_paths, GITHUB_CONNECTED_PATHS, failures)
    _expect_exact("android-connected-test.yml pull_request paths", pr_paths, GITHUB_CONNECTED_PATHS, failures)

    crons = _schedule_crons(GITHUB_WORKFLOWS / "codeql.yml")
    if CODEQL_WEEKLY_CRON not in crons:
        failures.append(f"codeql.yml: missing weekly schedule cron {CODEQL_WEEKLY_CRON!r}")


def _audit_gitea_fallback_policy(failures: list[str]) -> None:
    for workflow_name in ("windows-ci.yml", "android-connected.yml"):
        path = GITEA_WORKFLOWS / workflow_name
        _expect_exact(f"{workflow_name} push branches", _branches(path, "push"), GITEA_WORK_BRANCHES, failures)
        if not _event_present(path, "workflow_dispatch"):
            failures.append(f"{workflow_name}: missing workflow_dispatch trigger")

    connected = GITEA_WORKFLOWS / "android-connected.yml"
    _expect_exact("android-connected.yml push paths", _paths(connected, "push"), GITEA_CONNECTED_PATHS, failures)


def main() -> int:
    try:
        platforms = selected_ci_platforms()
    except ValueError as exc:
        print(f"=== CI trigger policy audit: FAIL ===\n  {exc}")
        return 1
    failures: list[str] = []
    if "GitHub" in platforms:
        _audit_github_main_pr_policy(failures)
    if "Gitea" in platforms:
        _audit_gitea_fallback_policy(failures)
    if failures:
        print("=== CI trigger policy audit: FAIL ===")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print(
        "PASS: selected CI provider trigger policy is pinned."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
