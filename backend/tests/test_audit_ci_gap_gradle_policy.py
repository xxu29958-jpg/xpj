from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from tests._infra.ci_gap import load_ci_gap_audit as _load


def _prevalidated_powershell_command(mod: object, workflow: Path, text: str) -> object:
    """Build the same command shape emitted after workflow parsing.

    This release-grouping test is platform independent; PowerShell AST behavior
    is covered separately and must not depend on pwsh being installed on Linux.
    """
    return mod.WorkflowCommand(  # type: ignore[attr-defined]
        workflow,
        text,
        shell="powershell",
        powershell_ast_digest=sha256(text.encode("utf-8")).hexdigest(),
    )


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
        _prevalidated_powershell_command(
            mod,
            workflow,
            ".\\gradlew.bat --no-daemon :app:assembleGrayRelease",
        ),
        _prevalidated_powershell_command(
            mod,
            workflow,
            ".\\gradlew.bat --no-daemon :app:assembleInternalRelease",
        ),
    ]
    expected = [
        "Gitea Android release APK builds must run gray/internal release tasks in one bounded-worker Gradle invocation"
    ]
    assert mod._gitea_ci_release_apk_policy_violations(split) == expected

    combined = _prevalidated_powershell_command(
        mod,
        workflow,
        ".\\gradlew.bat --no-daemon --max-workers=2 "
        ":app:assembleGrayRelease :app:assembleInternalRelease",
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
    for arguments in (
        ":app:testGrayDebugUnitTest -m",
        "--dry-run :app:testGrayDebugUnitTest",
        ":app:testGrayDebugUnitTest --task-graph",
        ":app:testGrayDebugUnitTest -x testGrayDebugUnitTest",
        ":app:testGrayDebugUnitTest -x:app:testGrayDebugUnitTest",
        ":app:testGrayDebugUnitTest --exclude-task=:app:testGrayDebugUnitTest",
        ":app:testGrayDebugUnitTest -x :app:tGDU",
        ":app:testGrayDebugUnitTest --exclude-task unrelatedTask",
    ):
        non_executing = mod.WorkflowCommand(
            Path("C:/.github/workflows/ci.yml"),
            f"./gradlew --no-daemon {arguments}",
        )
        assert ":app:testGrayDebugUnitTest" in mod._missing_gradle_tasks([non_executing])

    timed = mod.WorkflowCommand(
        Path("C:/.github/workflows/android-connected-test.yml"),
        "timeout --signal=INT --kill-after=30s 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
    )
    assert ":app:connectedGrayDebugAndroidTest" not in mod._missing_gradle_tasks([timed])
    separate_values = mod.WorkflowCommand(
        Path("C:/.github/workflows/android-connected-test.yml"),
        "timeout --signal INT --kill-after 30s 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
    )
    assert ":app:connectedGrayDebugAndroidTest" not in mod._missing_gradle_tasks(
        [separate_values]
    )
    attached_short_values = mod.WorkflowCommand(
        Path("C:/.github/workflows/android-connected-test.yml"),
        "timeout -v -sINT -k30s 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
    )
    assert ":app:connectedGrayDebugAndroidTest" not in mod._missing_gradle_tasks(
        [attached_short_values]
    )
    for invalid_wrapper in (
        "timeout 18m echo ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout --unknown 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout --signal= 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout --signal=NO_SUCH_SIGNAL 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout --signal=0 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout --kill-after=not-a-duration 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout -s=INT 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout -k=15s 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
        "timeout --signal --foreground 18m ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest",
    ):
        candidate = mod.WorkflowCommand(
            Path("C:/.github/workflows/android-connected-test.yml"),
            invalid_wrapper,
        )
        assert ":app:connectedGrayDebugAndroidTest" in mod._missing_gradle_tasks([candidate])


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
