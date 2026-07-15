from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_gap_audit


@pytest.mark.parametrize("platform", ["GitHub", "Gitea"])
def test_postgres_lanes_must_share_one_ordered_job(platform: str) -> None:
    mod = load_ci_gap_audit()
    workflow_part = ".github" if platform == "GitHub" else ".gitea"
    workflow = Path(workflow_part) / "workflows" / "ci.yml"
    other_part = ".gitea" if platform == "GitHub" else ".github"
    other_workflow = Path(other_part) / "workflows" / "ci.yml"
    commands = [
        mod.WorkflowCommand(
            workflow,
            "python scripts/run_test_lanes.py parallel",
            job="parallel-db",
            step_index=1,
        ),
        mod.WorkflowCommand(
            workflow,
            "python scripts/run_test_lanes.py stateful",
            job="stateful-db",
            step_index=1,
        ),
        mod.WorkflowCommand(
            other_workflow,
            "python scripts/run_test_lanes.py parallel",
            job="backend-db",
            step_index=1,
        ),
        mod.WorkflowCommand(
            other_workflow,
            "python scripts/run_test_lanes.py stateful",
            job="backend-db",
            step_index=2,
        ),
    ]

    assert mod._pytest_lane_sequence_violations(commands) == [
        f"{platform}: PostgreSQL parallel and stateful lanes must run "
        "in that order within one protected job"
    ]

    commands[1] = replace(commands[1], job="parallel-db", step_index=2)
    assert mod._pytest_lane_sequence_violations(commands) == []
