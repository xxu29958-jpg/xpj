from __future__ import annotations

import shutil
from pathlib import Path

from tests._infra.ci_gap import load_ci_script
from tests._infra.paths import REPOSITORY_ROOT

trigger_policy = load_ci_script("_audit_ci_trigger_policy.py")
workflow_yaml = load_ci_script("ci_gap_workflow_yaml.py")


def _github_workflows(tmp_path: Path, monkeypatch) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    for name in trigger_policy.GITHUB_WORKFLOW_EVENTS:
        shutil.copy2(REPOSITORY_ROOT / ".github" / "workflows" / name, workflows)
    monkeypatch.setattr(trigger_policy, "GITHUB_WORKFLOWS", workflows)
    return workflows


def _github_failures() -> list[str]:
    failures: list[str] = []
    trigger_policy._audit_github_main_pr_policy(failures)
    return failures


def test_pull_request_activity_filter_cannot_narrow_required_ci(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workflows = _github_workflows(tmp_path, monkeypatch)
    workflow = workflows / "ci.yml"
    source = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        source.replace(
            "  pull_request:\n    branches:",
            "  pull_request:\n    types: [closed]\n    branches:",
            1,
        ),
        encoding="utf-8",
    )

    assert any("pull_request configuration keys" in item for item in _github_failures())


def test_schedule_set_is_exact(tmp_path: Path, monkeypatch) -> None:
    workflows = _github_workflows(tmp_path, monkeypatch)
    workflow = workflows / "codeql.yml"
    source = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        source.replace(
            '    - cron: "37 3 * * 1"',
            '    - cron: "37 3 * * 1"\n    - cron: "*/5 * * * *"',
            1,
        ),
        encoding="utf-8",
    )

    assert any("schedule crons" in item for item in _github_failures())


def test_unexpected_trigger_event_is_rejected(tmp_path: Path, monkeypatch) -> None:
    workflows = _github_workflows(tmp_path, monkeypatch)
    workflow = workflows / "ci.yml"
    source = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        source.replace("permissions:\n", '  schedule:\n    - cron: "*/5 * * * *"\n\npermissions:\n', 1),
        encoding="utf-8",
    )

    assert any("trigger events" in item for item in _github_failures())


def test_duplicate_workflow_mapping_keys_fail_closed(tmp_path: Path) -> None:
    workflow = tmp_path / "duplicate.yml"
    workflow.write_text(
        """
on:
  pull_request:
    branches: [main]
  pull_request:
    branches: [develop]
jobs: {}
""",
        encoding="utf-8",
    )

    try:
        workflow_yaml.load_workflow(workflow)
    except ValueError as exc:
        assert "duplicate key 'pull_request'" in str(exc)
    else:
        raise AssertionError("duplicate workflow keys must fail closed")
