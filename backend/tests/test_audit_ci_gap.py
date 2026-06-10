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
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  backend:
    steps:
      - name: Comment only
        # python scripts\\smoke_test.py
        # python scripts\\check_api_contract.py
        run: |
          # python scripts\\release_audit.py
          python -m pytest tests
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    # YAML step comments AND #-commented lines inside the run body are both
    # invisible to the gate; the live pytest line lacks the backend suite's
    # ``-p no:cacheprovider`` anchor, so every requirement is missing.
    assert mod._missing_ci_invocations(commands) == [
        "release audit aggregator",
        "pytest full-suite lane",
        "end-to-end smoke",
        "API contract check",
        "backend ruff lint",
        "backend compileall",
    ]


def test_ci_gap_accepts_required_commands_across_workflows(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  backend:
    steps:
      - run: |
          .\\.ci-venv\\Scripts\\python.exe -m compileall app scripts tests
          .\\.ci-venv\\Scripts\\ruff.exe check app scripts tests
          .\\.ci-venv\\Scripts\\python.exe scripts\\release_audit.py
          .\\.ci-venv\\Scripts\\python.exe scripts\\check_api_contract.py
""",
        encoding="utf-8",
    )
    (workflows / "backend-postgres.yml").write_text(
        """
name: Backend PostgreSQL
jobs:
  backend-postgres:
    steps:
      - run: |
          .\\.ci-venv\\Scripts\\python.exe scripts\\smoke_test.py
          .\\.ci-venv\\Scripts\\python.exe -m pytest -q -ra --tb=short -p no:cacheprovider
  android:
    steps:
      - run: ./gradlew --no-daemon :app:testGrayDebugUnitTest :app:assertAndroidTestCountEqualsBaseline :app:assembleGrayDebug :app:assembleInternalDebug :app:lintGrayDebug
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == []
    assert mod._missing_gradle_tasks(commands) == []


def test_ci_gap_ignores_if_false_steps(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
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
          python -m pytest -q -p no:cacheprovider
          python scripts\\smoke_test.py
          python scripts\\check_api_contract.py
          ruff check app scripts tests
          python -m compileall app scripts tests
      - run: ./gradlew --no-daemon :app:testGrayDebugUnitTest
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == [
        "release audit aggregator",
        "pytest full-suite lane",
        "end-to-end smoke",
        "API contract check",
        "backend ruff lint",
        "backend compileall",
    ]


def test_ci_gap_ignores_if_false_jobs(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
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
          python -m pytest -q -p no:cacheprovider
          python scripts\\smoke_test.py
          python scripts\\check_api_contract.py
          ruff check app scripts tests
          python -m compileall app scripts tests
  android:
    steps:
      - run: ./gradlew --no-daemon :app:testGrayDebugUnitTest
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == [
        "release audit aggregator",
        "pytest full-suite lane",
        "end-to-end smoke",
        "API contract check",
        "backend ruff lint",
        "backend compileall",
    ]
