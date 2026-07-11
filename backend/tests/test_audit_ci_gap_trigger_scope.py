from __future__ import annotations

from pathlib import Path

from tests._infra.ci_gap import load_ci_gap_audit

_ANDROID_PATHS = """
      - android/app/src/**
      - android/gradle/**
      - android/app/build.gradle.kts
      - android/build.gradle.kts
      - android/gradle.properties
      - android/gradlew
      - android/gradlew.bat
      - android/settings.gradle.kts
      - .gitea/workflows/android-connected.yml
"""


def test_protected_inventory_rejects_wrong_branch_and_partial_paths(
    tmp_path: Path,
) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "wrong-branch.yml").write_text(
        """
on:
  pull_request:
    branches: [develop]
jobs:
  checks:
    steps:
      - run: python scripts/release_audit.py
""",
        encoding="utf-8",
    )
    (workflows / "partial-path.yml").write_text(
        """
on:
  pull_request:
    branches: [main]
    paths: [docs/**]
jobs:
  checks:
    steps:
      - run: python scripts/release_audit.py
""",
        encoding="utf-8",
    )
    (workflows / "tag-only.yml").write_text(
        """
on:
  pull_request:
    tags: [v*]
jobs:
  checks:
    steps:
      - run: python scripts/release_audit.py
""",
        encoding="utf-8",
    )
    (workflows / "closed-only.yml").write_text(
        """
on:
  pull_request:
    branches: [main]
    types: [closed]
jobs:
  checks:
    steps:
      - run: python scripts/release_audit.py
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert commands == []
    assert "release audit aggregator" in mod._missing_ci_invocations(commands)


def test_android_path_scope_can_only_prove_connected_test(tmp_path: Path) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    workflow = workflows / "android-connected.yml"
    workflow.write_text(
        f"""
on:
  push:
    branches: [main]
    paths:
{_ANDROID_PATHS}
jobs:
  connected:
    steps:
      - run: .\\gradlew.bat --no-daemon :app:connectedGrayDebugAndroidTest
      - run: python scripts/release_audit.py
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert {command.protection_scope for command in commands} == {"android"}
    assert "Gitea: release audit aggregator" in (
        mod._missing_ci_invocations_by_platform(commands)
    )
    missing_gradle = mod._missing_gradle_tasks_by_platform(commands)
    assert "Gitea: :app:connectedGrayDebugAndroidTest" not in missing_gradle


def test_multiline_lastexitcode_branch_cannot_hide_required_command(
    tmp_path: Path,
) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "windows-ci.yml").write_text(
        """
on:
  push:
    branches: [main]
jobs:
  checks:
    defaults:
      run:
        shell: powershell
    steps:
      - run: |
          if ($LASTEXITCODE -eq 0) {
            python scripts/release_audit.py
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          }
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert len(commands) == 1 and commands[0].text.strip() == ""
    assert "release audit aggregator" in mod._missing_ci_invocations(commands)
