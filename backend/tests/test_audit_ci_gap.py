from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load() -> object:
    return importlib.reload(importlib.import_module("_audit_ci_gap"))


def test_ci_gap_scans_run_commands_not_comments(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  backend:
    steps:
      - name: Comment only
        # python scripts\\release_audit.py
        run: python -m pytest tests
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == [
        "release audit aggregator",
        "pytest coverage lane",
        "file-backed pytest lane",
    ]


def test_ci_gap_accepts_required_commands_across_workflows(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  backend:
    steps:
      - run: |
          python scripts\\release_audit.py
          python -m pytest --cov=app --cov-report=term-missing
          python -m pytest -q -m file_backed_only
  android:
    steps:
      - run: ./gradlew --no-daemon :app:testGrayDebugUnitTest :app:assembleGrayDebug :app:assembleInternalDebug :app:lintGrayDebug
""",
        encoding="utf-8",
    )
    (workflows / "android-connected-test.yml").write_text(
        """
name: Android Connected Test
jobs:
  connected:
    steps:
      - run: ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == []
    assert mod._missing_gradle_tasks(commands) == []
