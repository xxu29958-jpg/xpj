"""Protected-event branch and path coverage for CI command inventory."""

from __future__ import annotations

import fnmatch
import pathlib
import re

_ANDROID_PROTECTED_PATHS = frozenset(
    {
        "android/app/src/**",
        "android/gradle/**",
        "android/app/build.gradle.kts",
        "android/build.gradle.kts",
        "android/gradle.properties",
        "android/gradlew",
        "android/gradlew.bat",
        "android/settings.gradle.kts",
    }
)
_STATUS_FUNCTION = re.compile(r"(?i)\b(success|always|failure|cancelled)\s*\(")


def workflow_action_requires_prior_success(value: object) -> bool:
    if value is None or value is True:
        return True
    if not isinstance(value, str):
        return False
    expression = value.strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    status_functions = {match.lower() for match in _STATUS_FUNCTION.findall(expression)}
    if not status_functions:
        return True
    if status_functions != {"success"} or "||" in expression:
        return False
    return any(
        re.fullmatch(r"\(*\s*success\(\)\s*\)*", term, re.IGNORECASE)
        for term in expression.split("&&")
    )


def _event_configuration(
    workflow: dict[object, object], event_name: str
) -> dict[object, object] | None:
    trigger = workflow.get("on")
    if isinstance(trigger, str):
        return {} if trigger == event_name else None
    if isinstance(trigger, list):
        return {} if event_name in {str(event) for event in trigger} else None
    if not isinstance(trigger, dict) or event_name not in trigger:
        return None
    configuration = trigger[event_name]
    if configuration is None:
        return {}
    return configuration if isinstance(configuration, dict) else None


def _string_patterns(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return None


def _ordered_pattern_match(value: str, patterns: tuple[str, ...]) -> bool:
    matched = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        candidate = pattern[1:] if negated else pattern
        if candidate and fnmatch.fnmatchcase(value, candidate):
            matched = not negated
    return matched


def _event_covers_main_branch(configuration: dict[object, object]) -> bool:
    branches = _string_patterns(configuration.get("branches"))
    ignored = _string_patterns(configuration.get("branches-ignore"))
    if branches is None or ignored is None:
        return False
    tag_filtered = (
        configuration.get("tags") is not None
        or configuration.get("tags-ignore") is not None
    )
    if tag_filtered and not branches:
        return False
    if branches and not _ordered_pattern_match("main", branches):
        return False
    return not (ignored and _ordered_pattern_match("main", ignored))


def _workflow_relative_path(path: pathlib.Path) -> str:
    for root in (".github", ".gitea"):
        if root in path.parts:
            index = path.parts.index(root)
            return "/".join(path.parts[index:])
    return path.as_posix()


def _protected_path_scope(
    path: pathlib.Path,
    configuration: dict[object, object],
) -> str | None:
    if configuration.get("paths-ignore") is not None:
        return None
    paths = _string_patterns(configuration.get("paths"))
    if paths is None:
        return None
    if not paths:
        return "full"
    normalized = {item.replace("\\", "/").removeprefix("./") for item in paths}
    if not _ANDROID_PROTECTED_PATHS.issubset(normalized):
        return None
    if _workflow_relative_path(path) not in normalized:
        return None
    return "android"


def protected_workflow_scope(
    path: pathlib.Path,
    workflow: dict[object, object],
    event_name: str,
) -> str | None:
    configuration = _event_configuration(workflow, event_name)
    if (
        configuration is None
        or configuration.get("types") is not None
        or not _event_covers_main_branch(configuration)
    ):
        return None
    return _protected_path_scope(path, configuration)
