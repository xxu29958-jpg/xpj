"""Prove path-scoped Windows qualification still runs for full release events."""

from __future__ import annotations

import pathlib
from collections.abc import Callable

from ci_gap_required_commands import (
    PATH_SCOPED_CI_INVOCATIONS,
    REQUIRED_CI_ACTIONS_BY_PLATFORM,
    REQUIRED_CI_INVOCATIONS,
    REQUIRED_CI_INVOCATIONS_BY_PLATFORM,
    REQUIRED_INSTALLER_POST_UPLOAD_INVOCATION_BY_PLATFORM,
)
from ci_gap_workflow_parser import (
    WorkflowCommand,
    _iter_workflow_actions,
    _iter_workflow_run_commands,
)

SegmentReader = Callable[[list[WorkflowCommand]], list[str]]


def github_qualification_event_violations(
    workflow_dirs: list[pathlib.Path],
    *,
    segment_reader: SegmentReader,
) -> list[str]:
    required_commands = [
        required
        for required in REQUIRED_CI_INVOCATIONS
        if required.label in PATH_SCOPED_CI_INVOCATIONS
    ]
    required_commands.extend(REQUIRED_CI_INVOCATIONS_BY_PLATFORM["GitHub"])
    required_commands.append(
        REQUIRED_INSTALLER_POST_UPLOAD_INVOCATION_BY_PLATFORM["GitHub"]
    )
    violations: list[str] = []
    for event_name in ("push", "workflow_dispatch"):
        commands = [
            command
            for command in _iter_workflow_run_commands(
                workflow_dirs,
                protected_only=True,
                protected_event=event_name,
            )
            if ".github" in command.workflow.parts
        ]
        actions = [
            action
            for action in _iter_workflow_actions(
                workflow_dirs,
                protected_only=True,
                protected_event=event_name,
            )
            if ".github" in action.workflow.parts
        ]
        segments = segment_reader(commands)
        for required in required_commands:
            if not any(required.matches(segment) for segment in segments):
                violations.append(f"GitHub {event_name} must run {required.label}")
        for required in REQUIRED_CI_ACTIONS_BY_PLATFORM["GitHub"]:
            if not any(
                required.matches(action.uses, action.inputs)
                for action in actions
            ):
                violations.append(f"GitHub {event_name} must run {required.label}")
    return violations
