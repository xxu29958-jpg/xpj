from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "_audit_ci_gap.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("_audit_ci_gap", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ci_gap_release_apk_policy_ignores_heredoc_diagnostic_text(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: |
          cat <<EOF
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
          EOF
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert ":app:assembleInternalRelease" in mod._missing_gradle_tasks(commands)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_checks_gradle_after_output_command_chain(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: |
          echo "cleanup" && ./gradlew --no-daemon --stop
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub CI must not call gradlew --stop during Android lanes"
    ]


def test_ci_gap_release_apk_policy_folds_yaml_output_command_text(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: >
          echo
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_keeps_command_before_heredoc(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: |
          ./gradlew --no-daemon --stop <<EOF
          diagnostic body
          EOF
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub CI must not call gradlew --stop during Android lanes"
    ]


def test_ci_gap_release_apk_policy_preserves_folded_yaml_blank_line_breaks(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: >
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease

          ./gradlew --no-daemon --max-workers=1 :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_keeps_command_after_heredoc_operator(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: |
          cat <<EOF && ./gradlew --no-daemon --stop
          diagnostic body
          EOF
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub CI must not call gradlew --stop during Android lanes"
    ]


def test_ci_gap_release_apk_policy_keeps_folded_comment_lines_until_shell_parse(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: >
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease
          # disabled
          :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert ":app:assembleInternalRelease" in mod._missing_gradle_tasks(commands)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_accepts_heredoc_delimiter_shell_word(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: |
          cat <<END-MARKER
          diagnostic body
          END-MARKER
          ./gradlew --no-daemon --stop
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub CI must not call gradlew --stop during Android lanes"
    ]
