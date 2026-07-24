"""Read-only audit: cloud and fallback CI trigger policy stays intentional."""

from __future__ import annotations

import pathlib
import sys

from ci_audit_provider import selected_ci_platforms
from ci_gap_trigger_scope import ANDROID_PROTECTED_PATHS
from ci_gap_workflow_yaml import load_workflow

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
GITHUB_WORKFLOW_EVENTS = {
    "ci.yml": ("push", "pull_request", "workflow_dispatch"),
    "android-connected-test.yml": ("push", "pull_request", "workflow_dispatch"),
    "codeql.yml": ("push", "pull_request", "workflow_dispatch", "schedule"),
}
GITHUB_EVENT_KEYS = {
    ("ci.yml", "push"): ("branches",),
    ("ci.yml", "pull_request"): ("branches",),
    ("android-connected-test.yml", "push"): ("branches", "paths"),
    ("android-connected-test.yml", "pull_request"): ("branches", "paths"),
    ("codeql.yml", "push"): ("branches",),
    ("codeql.yml", "pull_request"): ("branches",),
}
GITEA_WORKFLOW_EVENTS = {
    "windows-ci.yml": ("push", "workflow_dispatch"),
    "android-connected.yml": ("push", "workflow_dispatch"),
}
GITEA_EVENT_KEYS = {
    ("windows-ci.yml", "push"): ("branches",),
    ("android-connected.yml", "push"): ("branches", "paths"),
}


def _event_configuration(
    path: pathlib.Path,
    event_name: str,
) -> dict[object, object] | None:
    trigger = load_workflow(path).get("on")
    if isinstance(trigger, str):
        return {} if trigger == event_name else None
    if isinstance(trigger, list):
        return {} if event_name in {str(item) for item in trigger} else None
    if not isinstance(trigger, dict) or event_name not in trigger:
        return None
    configuration = trigger[event_name]
    if configuration is None:
        return {}
    if not isinstance(configuration, dict):
        raise ValueError(f"workflow event must be a mapping: {path}: {event_name}")
    return configuration


def _event_present(path: pathlib.Path, event_name: str) -> bool:
    return _event_configuration(path, event_name) is not None


def _trigger_mapping(path: pathlib.Path) -> dict[object, object]:
    trigger = load_workflow(path).get("on")
    if not isinstance(trigger, dict):
        raise ValueError(f"workflow on trigger must be a mapping: {path}")
    return trigger


def _mapping_keys(
    mapping: dict[object, object],
    *,
    label: str,
) -> tuple[str, ...]:
    if any(not isinstance(key, str) for key in mapping):
        raise ValueError(f"{label} keys must be strings")
    return tuple(mapping)


def _event_names(path: pathlib.Path) -> tuple[str, ...]:
    return _mapping_keys(_trigger_mapping(path), label=f"workflow trigger {path}")


def _event_keys(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    configuration = _event_configuration(path, event_name)
    if configuration is None:
        return ()
    return _mapping_keys(
        configuration,
        label=f"workflow event {path}: {event_name}",
    )


def _sequence_values(
    path: pathlib.Path,
    event_name: str,
    key: str,
) -> tuple[str, ...]:
    configuration = _event_configuration(path, event_name)
    if configuration is None or key not in configuration:
        return ()
    values = configuration[key]
    if not isinstance(values, list) or any(
        not isinstance(value, str) for value in values
    ):
        raise ValueError(
            f"workflow event {key} must be a string sequence: {path}: {event_name}"
        )
    return tuple(values)


def _branches(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    return _sequence_values(path, event_name, "branches")


def _paths(path: pathlib.Path, event_name: str) -> tuple[str, ...]:
    return _sequence_values(path, event_name, "paths")


def _schedule_crons(path: pathlib.Path) -> tuple[str, ...]:
    trigger = load_workflow(path).get("on")
    if not isinstance(trigger, dict) or "schedule" not in trigger:
        return ()
    schedules = trigger["schedule"]
    if not isinstance(schedules, list):
        raise ValueError(f"workflow schedule must be a sequence: {path}")
    crons: list[str] = []
    for schedule in schedules:
        if (
            not isinstance(schedule, dict)
            or set(_mapping_keys(schedule, label=f"workflow schedule {path}"))
            != {"cron"}
            or not isinstance(schedule.get("cron"), str)
        ):
            raise ValueError(
                f"workflow schedule entry must contain a cron string: {path}"
            )
        crons.append(schedule["cron"])
    return tuple(crons)


def _expect_exact(label: str, actual: tuple[str, ...], expected: tuple[str, ...], failures: list[str]) -> None:
    if actual != expected:
        failures.append(f"{label}: expected {list(expected)}, got {list(actual)}")


def _expect_exact_members(
    label: str,
    actual: tuple[str, ...],
    expected: tuple[str, ...],
    failures: list[str],
) -> None:
    if set(actual) != set(expected):
        failures.append(
            f"{label}: expected members {sorted(expected)}, got {sorted(actual)}"
        )


def _audit_github_main_pr_policy(failures: list[str]) -> None:
    for workflow_name, expected_events in GITHUB_WORKFLOW_EVENTS.items():
        path = GITHUB_WORKFLOWS / workflow_name
        _expect_exact_members(
            f"{workflow_name} trigger events",
            _event_names(path),
            expected_events,
            failures,
        )
        _expect_exact(f"{workflow_name} push branches", _branches(path, "push"), GITHUB_MAIN_ONLY, failures)
        _expect_exact(
            f"{workflow_name} pull_request branches",
            _branches(path, "pull_request"),
            GITHUB_MAIN_ONLY,
            failures,
        )
        if not _event_present(path, "workflow_dispatch"):
            failures.append(f"{workflow_name}: missing workflow_dispatch trigger")
        for event_name in ("push", "pull_request"):
            _expect_exact_members(
                f"{workflow_name} {event_name} configuration keys",
                _event_keys(path, event_name),
                GITHUB_EVENT_KEYS[(workflow_name, event_name)],
                failures,
            )

    connected = GITHUB_WORKFLOWS / "android-connected-test.yml"
    push_paths = _paths(connected, "push")
    pr_paths = _paths(connected, "pull_request")
    _expect_exact("android-connected-test.yml push paths", push_paths, GITHUB_CONNECTED_PATHS, failures)
    _expect_exact("android-connected-test.yml pull_request paths", pr_paths, GITHUB_CONNECTED_PATHS, failures)

    crons = _schedule_crons(GITHUB_WORKFLOWS / "codeql.yml")
    _expect_exact(
        "codeql.yml schedule crons",
        crons,
        (CODEQL_WEEKLY_CRON,),
        failures,
    )


def _audit_gitea_fallback_policy(failures: list[str]) -> None:
    for workflow_name, expected_events in GITEA_WORKFLOW_EVENTS.items():
        path = GITEA_WORKFLOWS / workflow_name
        _expect_exact_members(
            f"{workflow_name} trigger events",
            _event_names(path),
            expected_events,
            failures,
        )
        _expect_exact(f"{workflow_name} push branches", _branches(path, "push"), GITEA_WORK_BRANCHES, failures)
        _expect_exact_members(
            f"{workflow_name} push configuration keys",
            _event_keys(path, "push"),
            GITEA_EVENT_KEYS[(workflow_name, "push")],
            failures,
        )
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
    try:
        if "GitHub" in platforms:
            _audit_github_main_pr_policy(failures)
        if "Gitea" in platforms:
            _audit_gitea_fallback_policy(failures)
    except (OSError, ValueError) as exc:
        failures.append(str(exc))
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
