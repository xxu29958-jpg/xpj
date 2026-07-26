"""Read-only audit: cloud and fallback CI trigger policy stays intentional."""

from __future__ import annotations

import pathlib
import sys

from ci_audit_provider import selected_ci_platforms
from ci_gap_trigger_scope import ANDROID_PROTECTED_PATHS
from ci_gap_workflow_parser import iter_workflow_paths, load_workflow

ROOT = pathlib.Path(__file__).resolve().parents[2]
GITHUB_WORKFLOWS = ROOT / ".github" / "workflows"
GITEA_WORKFLOWS = ROOT / ".gitea" / "workflows"

GITHUB_MAIN_ONLY = ("main",)
GITEA_WORK_BRANCHES = ("main", "feat/**", "fix/**", "perf/**", "refactor/**", "codex/**")
CODEQL_WEEKLY_CRON = "37 3 * * 1"
QUALIFICATION_DISPATCH_TYPE = "qualification"
NVD_REFRESH_DISPATCH_TYPE = "nvd_database_refresh"
GITEA_CONNECTED_PATHS = (
    *ANDROID_PROTECTED_PATHS,
    ".gitea/workflows/android-connected.yml",
)


def _events(path: pathlib.Path) -> dict[str, object]:
    raw_events = load_workflow(path).get("on")
    if isinstance(raw_events, str):
        return {raw_events: None}
    if isinstance(raw_events, list) and all(
        isinstance(event, str) for event in raw_events
    ):
        return dict.fromkeys(raw_events)
    if isinstance(raw_events, dict) and all(
        isinstance(event, str) for event in raw_events
    ):
        return dict(raw_events)
    return {}


def _event_present(path: pathlib.Path, event_name: str) -> bool:
    return event_name in _events(path)


def _event_values(
    path: pathlib.Path,
    event_name: str,
    field: str,
) -> tuple[str, ...]:
    raw_event = _events(path).get(event_name)
    if not isinstance(raw_event, dict):
        return ()
    values = raw_event.get(field)
    if isinstance(values, str):
        return (values,)
    if isinstance(values, list) and all(isinstance(value, str) for value in values):
        return tuple(values)
    return ()


def _branches(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    return _event_values(path, event_name, "branches")


def _paths(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    return _event_values(path, event_name, "paths")


def _types(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    return _event_values(path, event_name, "types")


def _schedule_crons(path: pathlib.Path) -> tuple[str, ...]:
    schedule = _events(path).get("schedule")
    if not isinstance(schedule, list):
        return ()
    return tuple(
        cron
        for entry in schedule
        if isinstance(entry, dict)
        and isinstance((cron := entry.get("cron")), str)
    )


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
        if QUALIFICATION_DISPATCH_TYPE not in _types(path, "repository_dispatch"):
            failures.append(
                f"{path.name}: missing repository_dispatch type "
                f"{QUALIFICATION_DISPATCH_TYPE!r}"
            )
        for event_name in ("push", "pull_request"):
            for field in ("paths", "paths-ignore"):
                _expect_exact(
                    f"{workflow_name} {event_name} {field}",
                    _event_values(path, event_name, field),
                    (),
                    failures,
                )

    for path in iter_workflow_paths(GITHUB_WORKFLOWS):
        if (
            QUALIFICATION_DISPATCH_TYPE
            in _types(path, "repository_dispatch")
            and _event_present(path, "workflow_dispatch")
        ):
            failures.append(
                f"{path.name}: qualification workflow cannot expose workflow_dispatch"
            )

    nvd = GITHUB_WORKFLOWS / "nvd-database.yml"
    if NVD_REFRESH_DISPATCH_TYPE not in _types(nvd, "repository_dispatch"):
        failures.append(
            f"{nvd.name}: missing repository_dispatch type "
            f"{NVD_REFRESH_DISPATCH_TYPE!r}"
        )
    if _event_present(nvd, "workflow_dispatch"):
        failures.append(
            f"{nvd.name}: secret-bearing producer cannot expose workflow_dispatch"
        )

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
