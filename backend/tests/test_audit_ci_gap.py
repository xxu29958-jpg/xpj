from __future__ import annotations

from pathlib import Path

from tests._infra.ci_gap import load_ci_gap_audit as _load

_POSTGRES_REQUIRED_WORKFLOW = """
name: Backend PostgreSQL
jobs:
  backend-postgres:
    steps:
      - run: .\\.ci-venv\\Scripts\\python.exe scripts\\smoke_test.py
      - run: .\\.ci-venv\\Scripts\\python.exe scripts\\postgres_backup_drill.py
      - run: .\\.ci-venv\\Scripts\\python.exe -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4
      - run: .\\.ci-venv\\Scripts\\python.exe -m scripts.run_postgres_pytest_lane --lane real-db --workers 1
  android:
    steps:
      - run: ./gradlew --no-daemon :app:kspGrayDebugKotlin --rerun-tasks
      - run: ./gradlew --no-daemon :app:testGrayDebugUnitTest :app:assertAndroidTestCountEqualsBaseline :app:assembleGrayDebug :app:assembleInternalDebug :app:assembleGrayRelease :app:assembleInternalRelease :app:lintGrayDebug :app:detektGrayDebug :app:detektGrayDebugUnitTest
"""

_INSTALLER_SAFETY_COMMAND = (
    "python -m pytest packaging/tests --strict-markers "
    "-p no:cacheprovider -o addopts= -n 3 --dist loadgroup "
    "--max-worker-restart 0"
)
_SAFE_PYTEST_ENVIRONMENT = (("PYTEST_ADDOPTS", ""),)


def _write_required_workflows(workflows: Path) -> None:
    (workflows / "ci.yml").write_text(
        """
name: CI
env:
  pytest_addopts: "-k workflow_poison"
jobs:
  backend:
    env:
      PyTest_AddOpts: "-m job_poison"
    steps:
      - run: .\\.ci-venv\\Scripts\\python.exe -m compileall app scripts tests packaging/tests
      - run: .\\.ci-venv\\Scripts\\ruff.exe check app scripts tests packaging/tests
      - env:
          PYTEST_ADDOPTS: ""
        run: .\\.ci-venv\\Scripts\\python.exe -m pytest -q packaging/tests --strict-markers -p no:cacheprovider -o addopts= -n 2 --dist loadgroup --max-worker-restart 0
      - run: powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly
      - run: pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly
      - run: powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\\build_backend_exe.ps1 -Clean
      - run: .\\.ci-venv\\Scripts\\python.exe scripts\\release_audit.py
      - run: .\\.ci-venv\\Scripts\\python.exe scripts\\check_api_contract.py
  desktop:
    steps:
      - run: .\\.ci-venv\\Scripts\\python.exe -m compileall backend_manager tests
      - run: .\\.ci-venv\\Scripts\\ruff.exe check backend_manager tests
      - run: .\\.ci-venv\\Scripts\\python.exe -m pytest -q
""",
        encoding="utf-8",
    )
    (workflows / "backend-postgres.yml").write_text(
        _POSTGRES_REQUIRED_WORKFLOW,
        encoding="utf-8",
    )
    (workflows / "android-connected.yml").write_text(
        """
name: Android Connected
jobs:
  connected:
    steps:
      - run: .\\gradlew.bat --no-daemon :app:connectedGrayDebugAndroidTest
""",
        encoding="utf-8",
    )


def _assert_installer_safety_rejects_narrowing(mod: object) -> None:
    invalid_commands = (
        "python -m pytest -q packaging/tests -p no:cacheprovider -k version",
        (
            "python -m pytest -q packaging/tests --strict-markers "
            "-p no:cacheprovider -o addopts="
        ),
        _INSTALLER_SAFETY_COMMAND.replace(
            "--max-worker-restart 0",
            "--max-worker-restart 1",
        ),
    )
    for text in invalid_commands:
        command = mod.WorkflowCommand(
            Path("ci.yml"),
            text,
            environment=_SAFE_PYTEST_ENVIRONMENT,
        )
        assert "pytest installer safety lane" in mod._missing_ci_invocations(
            [command]
        )
    poisoned = mod.WorkflowCommand(
        Path("ci.yml"),
        _INSTALLER_SAFETY_COMMAND,
        environment=(("pytest_addopts", ""), ("PYTEST_ADDOPTS", "-k version")),
    )
    assert "pytest installer safety lane" in mod._missing_ci_invocations([poisoned])


def _assert_installer_safety_tuning_contract(mod: object) -> None:
    precedence = mod.WorkflowCommand(
        Path("ci.yml"),
        _INSTALLER_SAFETY_COMMAND,
        environment=(("PYTEST_ADDOPTS", "-k poisoned"), ("pytest_addopts", "")),
    )
    assert "pytest installer safety lane" not in mod._missing_ci_invocations(
        [precedence]
    )
    for workers in (2, 3, 4):
        tuned = mod.WorkflowCommand(
            Path("ci.yml"),
            _INSTALLER_SAFETY_COMMAND.replace("-n 3", f"-n {workers}"),
            environment=_SAFE_PYTEST_ENVIRONMENT,
        )
        assert "pytest installer safety lane" not in mod._missing_ci_invocations(
            [tuned]
        )
    invalid_commands = (
        _INSTALLER_SAFETY_COMMAND.replace("-n 3", "-n 1"),
        _INSTALLER_SAFETY_COMMAND.replace("-n 3", "-n 5"),
        _INSTALLER_SAFETY_COMMAND.replace(
            "-p no:cacheprovider",
            "-p no:cacheprovider -p no:cacheprovider",
        ),
        f"{_INSTALLER_SAFETY_COMMAND} tests/test_version.py",
    )
    for text in invalid_commands:
        invalid = mod.WorkflowCommand(
            Path("ci.yml"),
            text,
            environment=_SAFE_PYTEST_ENVIRONMENT,
        )
        assert "pytest installer safety lane" in mod._missing_ci_invocations(
            [invalid]
        )


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
        "pytest ordinary business lane",
        "pytest real-db serial lane",
        "pytest installer safety lane",
        "installer source preflight (Windows PowerShell 5.1)",
        "installer source preflight (PowerShell 7)",
        "frozen backend locked release build",
        "end-to-end smoke",
        "backup/restore drill",
        "API contract check",
        "backend ruff lint",
        "backend compileall",
        "desktop compileall",
        "desktop ruff lint",
        "desktop pytest",
    ]

def test_ci_gap_accepts_required_commands_across_workflows(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    _write_required_workflows(workflows)
    commands = mod._iter_workflow_run_commands(workflows)

    assert mod._missing_ci_invocations(commands) == []
    assert mod._missing_gradle_tasks(commands) == []
    installer_only = [command for command in commands if "packaging/tests" in command.text]
    assert "pytest ordinary business lane" in mod._missing_ci_invocations(installer_only)
    assert "pytest real-db serial lane" in mod._missing_ci_invocations(installer_only)
    assert "pytest installer safety lane" not in mod._missing_ci_invocations(installer_only)
    business_only = [
        command
        for command in commands
        if "scripts.run_postgres_pytest_lane" in command.text
    ]
    assert "pytest installer safety lane" in mod._missing_ci_invocations(business_only)
    assert "pytest ordinary business lane" not in mod._missing_ci_invocations(business_only)
    assert "pytest real-db serial lane" not in mod._missing_ci_invocations(business_only)
    narrowed_business = mod.WorkflowCommand(
        Path("ci.yml"),
        "python -m pytest tests/test_audit_ci_gap.py -q -ra --tb=short -p no:cacheprovider",
    )
    assert "pytest ordinary business lane" in mod._missing_ci_invocations([narrowed_business])
    assert "pytest real-db serial lane" in mod._missing_ci_invocations([narrowed_business])
    _assert_installer_safety_rejects_narrowing(mod)
    _assert_installer_safety_tuning_contract(mod)


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
          python scripts\\postgres_backup_drill.py
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
        "pytest ordinary business lane",
        "pytest real-db serial lane",
        "pytest installer safety lane",
        "installer source preflight (Windows PowerShell 5.1)",
        "installer source preflight (PowerShell 7)",
        "frozen backend locked release build",
        "end-to-end smoke",
        "backup/restore drill",
        "API contract check",
        "backend ruff lint",
        "backend compileall",
        "desktop compileall",
        "desktop ruff lint",
        "desktop pytest",
    ]


def test_ci_gap_blank_line_does_not_unmute_disabled_step(tmp_path: Path) -> None:
    """A blank line between ``if: false`` and ``run:`` has indent 0; it must
    not pop the disabled-step stack and let the muted run satisfy pins."""
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
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    assert "release audit aggregator" in mod._missing_ci_invocations(commands)


def test_ci_gap_ignores_if_false_job_declared_after_steps(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  disabled-installer:
    steps:
      - run: powershell -NoProfile -File packaging\\build_inno_installer.ps1
      - run: powershell -NoProfile -File packaging\\build_inno_installer.ps1 -VerifyOnly
    if: false
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)
    executable_segments = mod._iter_executable_command_segments(commands)
    compile_matcher, verify_matcher = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[
        "GitHub"
    ]

    assert not any(compile_matcher.matches(item) for item in executable_segments)
    assert not any(verify_matcher.matches(item) for item in executable_segments)


def test_ci_gap_gradle_prose_mention_does_not_satisfy(tmp_path: Path) -> None:
    """A task name inside echo/prose (no real gradlew invocation on the line)
    must not satisfy the gradle pins."""
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  android:
    steps:
      - run: |
          echo "we used to run :app:testGrayDebugUnitTest here"
          echo "./gradlew --no-daemon :app:testGrayDebugUnitTest"
          Write-Host ":app:lintGrayDebug moved elsewhere"
          Write-Host "./gradlew --no-daemon :app:lintGrayDebug"
          # powershell -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly
          echo "powershell -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly"
          Write-Host "powershell -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly"
          powershell -Command "Write-Host 'powershell -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly'"
          powershell -Command Write-Host -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly
          powershell -EncodedCommand ZgBhAGsAZQA= -File packaging\\build_inno_installer.ps1 -CheckSourceInputsOnly
          echo "powershell -File scripts\\build_backend_exe.ps1 -Clean"
          powershell -Command Write-Host -File scripts\\build_backend_exe.ps1 -Clean
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)

    missing = mod._missing_gradle_tasks(commands)
    assert ":app:testGrayDebugUnitTest" in missing
    assert ":app:lintGrayDebug" in missing
    assert "installer source preflight (Windows PowerShell 5.1)" in mod._missing_ci_invocations(commands)
    assert "installer source preflight (PowerShell 7)" in mod._missing_ci_invocations(commands)
    assert "frozen backend locked release build" in mod._missing_ci_invocations(commands)
    commands.append(
        mod.WorkflowCommand(
            Path("ci.yml"),
            "powershell -NoProfile -File packaging\\build_inno_installer.ps1 "
            "-CheckSourceInputsOnly",
        )
    )
    assert "installer source preflight (Windows PowerShell 5.1)" not in mod._missing_ci_invocations(commands)
    assert "installer source preflight (PowerShell 7)" in mod._missing_ci_invocations(commands)
    commands.append(
        mod.WorkflowCommand(
            Path("ci.yml"),
            "pwsh -NoProfile -File packaging\\build_inno_installer.ps1 "
            "-CheckSourceInputsOnly",
        )
    )
    assert "installer source preflight (PowerShell 7)" not in mod._missing_ci_invocations(commands)
    build_line = "powershell -NoProfile -File scripts\\build_backend_exe.ps1 -Clean"
    commands.append(mod.WorkflowCommand(Path("ci.yml"), build_line))
    assert "frozen backend locked release build" not in mod._missing_ci_invocations(commands)
    unsafe_gradle_lines = [
        "./gradlew --no-daemon :app:testGrayDebugUnitTest || true",
        "./gradlew --no-daemon :app:testGrayDebugUnitTest; exit 0",
        "./gradlew --no-daemon :app:testGrayDebugUnitTest | tee gradle.log",
        "./gradlew --no-daemon :app:testGrayDebugUnitTest && echo done",
    ]
    for line in unsafe_gradle_lines:
        unsafe = [mod.WorkflowCommand(Path("ci.yml"), line)]
        assert ":app:testGrayDebugUnitTest" in mod._missing_gradle_tasks(unsafe)


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
          python scripts\\postgres_backup_drill.py
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
        "pytest ordinary business lane",
        "pytest real-db serial lane",
        "pytest installer safety lane",
        "installer source preflight (Windows PowerShell 5.1)",
        "installer source preflight (PowerShell 7)",
        "frozen backend locked release build",
        "end-to-end smoke",
        "backup/restore drill",
        "API contract check",
        "backend ruff lint",
        "backend compileall",
        "desktop compileall",
        "desktop ruff lint",
        "desktop pytest",
    ]
