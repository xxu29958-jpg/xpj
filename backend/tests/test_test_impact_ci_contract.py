from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.parallel_safe

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def test_impact_shadow_is_advisory_and_executes_only_a_proven_selection() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    shadow = workflow["jobs"]["backend-impact-shadow"]
    assert shadow["if"] == "github.event_name == 'pull_request'"
    assert shadow["continue-on-error"] is True
    assert shadow["services"]["postgres"]["image"] == "postgres:17"
    steps = {step["name"]: step for step in shadow["steps"]}

    plan = steps["Build backend impact plan"]
    assert "python -m scripts.test_impact_selection" in plan["run"]
    assert "continue-on-error" not in plan
    assert plan["id"] == "impact_plan"

    execution = steps["Execute selected backend shadow"]
    assert execution["if"] == "steps.impact_plan.outputs.mode == 'selected'"
    assert "scripts/run_test_lanes.py impacted" in execution["run"]
    assert "--junit-dir" in execution["run"]
    assert "continue-on-error" not in execution

    evidence = steps["Upload backend impact evidence"]
    assert evidence["if"] == "always()"
    assert evidence["with"]["if-no-files-found"] == "error"

    full_steps = workflow["jobs"]["backend-postgres"]["steps"]
    assert any(
        "scripts/run_test_lanes.py parallel" in str(step.get("run", ""))
        for step in full_steps
    )
    assert any(
        "scripts/run_test_lanes.py stateful" in str(step.get("run", ""))
        for step in full_steps
    )
    assert not any(
        step.get("name") == "Build backend impact plan"
        for step in full_steps
    )


def test_shadow_plan_uses_full_history_and_exact_pr_comparison_refs() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    shadow_steps = workflow["jobs"]["backend-impact-shadow"]["steps"]
    checkout = next(
        step
        for step in shadow_steps
        if step.get("name") == "Checkout"
    )
    assert checkout["with"]["fetch-depth"] == 0
    plan = next(
        step
        for step in shadow_steps
        if step.get("name") == "Build backend impact plan"
    )
    assert plan["env"] == {
        "XPJ_IMPACT_BASE": "${{ github.event.pull_request.base.sha }}",
        "XPJ_IMPACT_HEAD": "${{ github.sha }}",
    }
