"""PostgreSQL lane ordering policy for the CI gap audit."""

from __future__ import annotations

import pathlib
from collections.abc import Callable

from ci_gap_required_commands import REQUIRED_CI_INVOCATIONS, RequiredCommand
from ci_gap_workflow_parser import WorkflowCommand

_PLATFORM_WORKFLOW_PARTS = {"GitHub": ".github", "Gitea": ".gitea"}
_LANE_REQUIREMENTS = {
    required.label: required
    for required in REQUIRED_CI_INVOCATIONS
    if required.label
    in {"pytest PostgreSQL parallel lane", "pytest stateful serial lane"}
}


def pytest_lane_sequence_violations(
    commands: list[WorkflowCommand],
    *,
    segment_reader: Callable[[list[WorkflowCommand]], list[str]],
) -> list[str]:
    """Require both PostgreSQL lanes to run sequentially in one protected job."""

    parallel = _LANE_REQUIREMENTS["pytest PostgreSQL parallel lane"]
    stateful = _LANE_REQUIREMENTS["pytest stateful serial lane"]
    violations: list[str] = []
    for platform, workflow_part in _PLATFORM_WORKFLOW_PARTS.items():
        positions_by_job = _lane_positions_by_job(
            commands,
            workflow_part=workflow_part,
            parallel=parallel,
            stateful=stateful,
            segment_reader=segment_reader,
        )
        if not _has_ordered_lane_pair(positions_by_job):
            violations.append(
                f"{platform}: PostgreSQL parallel and stateful lanes must run "
                "in that order within one protected job"
            )
    return violations


def _lane_positions_by_job(
    commands: list[WorkflowCommand],
    *,
    workflow_part: str,
    parallel: RequiredCommand,
    stateful: RequiredCommand,
    segment_reader: Callable[[list[WorkflowCommand]], list[str]],
) -> dict[tuple[pathlib.Path, str], dict[str, list[tuple[int, int]]]]:
    positions_by_job: dict[
        tuple[pathlib.Path, str], dict[str, list[tuple[int, int]]]
    ] = {}
    for command in commands:
        if workflow_part not in command.workflow.parts or command.protection_scope != "full":
            continue
        positions = positions_by_job.setdefault(
            (command.workflow, command.job),
            {"parallel": [], "stateful": []},
        )
        for segment_index, segment in enumerate(segment_reader([command])):
            position = (command.step_index, segment_index)
            if parallel.matches(segment):
                positions["parallel"].append(position)
            if stateful.matches(segment):
                positions["stateful"].append(position)
    return positions_by_job


def _has_ordered_lane_pair(
    positions_by_job: dict[
        tuple[pathlib.Path, str], dict[str, list[tuple[int, int]]]
    ],
) -> bool:
    return any(
        parallel_position < stateful_position
        for positions in positions_by_job.values()
        for parallel_position in positions["parallel"]
        for stateful_position in positions["stateful"]
    )
