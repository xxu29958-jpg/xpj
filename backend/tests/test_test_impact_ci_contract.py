from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.parallel_safe

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def test_impact_shadow_uses_the_package_entrypoint_and_cannot_fail_silently() -> None:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["backend-postgres"]["steps"]
        if step.get("name") == "Backend impact plan (shadow)"
    )

    assert "python -m scripts.test_impact_selection" in step["run"]
    assert "continue-on-error" not in step
