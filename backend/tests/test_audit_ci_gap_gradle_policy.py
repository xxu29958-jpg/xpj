from __future__ import annotations

from pathlib import Path

from tests._infra.ci_gap import load_ci_gap_audit as _load


def test_ci_gap_release_apk_policy_requires_real_single_github_invocation(tmp_path: Path) -> None:
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
          echo "./gradlew --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease"
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease
          ./gradlew --no-daemon --max-workers=1 :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_accepts_multiline_tokenized_invocation(tmp_path: Path) -> None:
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
          ./gradlew --no-daemon \\
            :app:assembleInternalRelease \\
            --max-workers 2 \\
            :app:assembleGrayRelease
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert mod._github_ci_release_apk_policy_violations(commands) == []

    unsafe = (workflows / "ci.yml").read_text(encoding="utf-8").replace(
        "--max-workers 2",
        "--max-workers 3",
    )
    (workflows / "ci.yml").write_text(unsafe, encoding="utf-8")
    commands = mod._iter_workflow_run_commands(workflows)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_gitea_release_apk_policy_requires_one_bounded_invocation() -> None:
    mod = _load()
    workflow = Path("C:/.gitea/workflows/windows-ci.yml")
    split = [
        mod.WorkflowCommand(
            workflow,
            ".\\gradlew.bat --no-daemon :app:assembleGrayRelease",
            shell="powershell",
        ),
        mod.WorkflowCommand(
            workflow,
            ".\\gradlew.bat --no-daemon :app:assembleInternalRelease",
            shell="powershell",
        ),
    ]
    expected = [
        "Gitea Android release APK builds must run gray/internal release tasks in one bounded-worker Gradle invocation"
    ]
    assert mod._gitea_ci_release_apk_policy_violations(split) == expected

    combined = mod.WorkflowCommand(
        workflow,
        ".\\gradlew.bat --no-daemon --max-workers=2 "
        ":app:assembleGrayRelease :app:assembleInternalRelease",
        shell="powershell",
    )
    assert mod._gitea_ci_release_apk_policy_violations([combined]) == []


def test_ci_gap_release_apk_policy_accepts_folded_yaml_invocation(tmp_path: Path) -> None:
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
          ./gradlew --no-daemon
          --max-workers=1
          :app:assembleGrayRelease
          :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert mod._github_ci_release_apk_policy_violations(commands) == []


def test_ci_gap_release_apk_policy_ignores_inline_shell_comments(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease # :app:assembleInternalRelease --stop
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert ":app:assembleInternalRelease" in mod._missing_gradle_tasks(commands)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_ignores_comments_after_shell_separator(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease ;# :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert ":app:assembleInternalRelease" in mod._missing_gradle_tasks(commands)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_splits_shell_command_operators(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease && ./gradlew --no-daemon --max-workers=1 :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]
    _assert_gradle_failure_masking_is_rejected(mod)


def _assert_gradle_failure_masking_is_rejected(mod: object) -> None:
    release = ":app:assembleGrayRelease :app:assembleInternalRelease"
    negated = mod.WorkflowCommand(
        Path("C:/.github/workflows/ci.yml"),
        f"! ./gradlew --no-daemon --max-workers=1 {release}",
    )
    assert mod._github_ci_release_apk_policy_violations([negated]) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]

    swallowed = mod.WorkflowCommand(
        Path("C:/.gitea/workflows/windows-ci.yml"),
        ".\\gradlew.bat --no-daemon :app:testGrayDebugUnitTest\nexit 0",
        shell="powershell",
    )
    assert ":app:testGrayDebugUnitTest" in mod._missing_gradle_tasks([swallowed])


def test_ci_gap_gradle_catch_must_propagate_guard_failure() -> None:
    mod = _load()
    workflow = Path("C:/.gitea/workflows/android-connected.yml")
    swallowed = mod.WorkflowCommand(
        workflow,
        r"""
try {
  .\gradlew.bat --no-daemon :app:connectedGrayDebugAndroidTest
  if ($LASTEXITCODE -ne 0) { throw "connected tests failed" }
}
catch {
  $failed = $true
}
if ($failed) { exit 1 }
""",
        shell="powershell",
    )
    assert ":app:connectedGrayDebugAndroidTest" in mod._missing_gradle_tasks([swallowed])

    rethrown = mod.WorkflowCommand(
        workflow,
        swallowed.text.replace("  $failed = $true", "  throw").replace(
            "\nif ($failed) { exit 1 }",
            "",
        ),
        shell="powershell",
    )
    assert ":app:connectedGrayDebugAndroidTest" not in mod._missing_gradle_tasks([rethrown])


def test_ci_gap_release_apk_policy_does_not_merge_literal_block_without_continuation(
    tmp_path: Path,
) -> None:
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
          ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease
          : :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub Android release APK builds must run gray/internal release tasks in one Gradle invocation"
    ]


def test_ci_gap_release_apk_policy_bans_github_gradle_stop_anywhere(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "android-connected-test.yml").write_text(
        """
name: Android Connected
jobs:
  connected:
    steps:
      - run: ./gradlew --no-daemon --stop
""",
        encoding="utf-8",
    )
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows)
    assert mod._github_ci_release_apk_policy_violations(commands) == [
        "GitHub CI must not call gradlew --stop during Android lanes"
    ]
