from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "_audit_ci_gap.py"


def _load() -> object:
    # Load straight from the file path instead of inserting backend/scripts onto
    # sys.path: a process-wide sys.path mutation here would shadow same-named
    # modules for every later test in the run. Register the module under its own
    # name first so dataclass annotation resolution (which looks the module up in
    # sys.modules) works during exec.
    spec = importlib.util.spec_from_file_location("_audit_ci_gap", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_ci_gap_ignores_if_false_steps(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  backend:
    steps:
      - name: disabled audit
        if: false
        run: |
          python scripts\\release_audit.py
          python -m pytest --cov=app
          python -m pytest -m file_backed_only
      - run: ./gradlew --no-daemon :app:testGrayDebugUnitTest
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == [
        "release audit aggregator",
        "pytest coverage lane",
        "file-backed pytest lane",
    ]


def test_ci_gap_ignores_if_false_jobs(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  disabled-backend:
    if: ${{ false }}
    steps:
      - run: |
          python scripts\\release_audit.py
          python -m pytest --cov=app
          python -m pytest -m file_backed_only
  android:
    steps:
      - run: ./gradlew --no-daemon :app:testGrayDebugUnitTest
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == [
        "release audit aggregator",
        "pytest coverage lane",
        "file-backed pytest lane",
    ]
