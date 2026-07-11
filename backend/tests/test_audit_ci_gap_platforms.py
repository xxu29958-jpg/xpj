from dataclasses import replace
from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_gap_audit

_INSTALLER_RUN_STEP = """
      - run: |
          powershell -NoProfile -File packaging\\build_inno_installer.ps1
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          powershell -NoProfile -File packaging\\build_inno_installer.ps1 -VerifyOnly
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
"""

_INSTALLER_VERIFY_FIRST_RUN_STEP = """
      - run: |
          powershell -NoProfile -File packaging\\build_inno_installer.ps1 -VerifyOnly
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          powershell -NoProfile -File packaging\\build_inno_installer.ps1
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
"""


def _installer_upload_step(action_sha: str, condition: str = "") -> str:
    condition_line = f"        if: {condition}\n" if condition else ""
    return f"""
      - uses: actions/upload-artifact@{action_sha}
{condition_line.rstrip()}
        with:
          name: ticketbox-windows-installer
          path: ${{{{ env.INSTALLER_PUBLISH_PATH }}}}
          if-no-files-found: error
"""


def _write_installer_workflow(
    path: Path,
    *,
    action_sha: str = "",
    upload_first: bool = False,
    upload_condition: str = "",
    verify_first: bool = False,
    include_run: bool = True,
) -> None:
    run_step = _INSTALLER_VERIFY_FIRST_RUN_STEP if verify_first else _INSTALLER_RUN_STEP
    steps = [run_step] if include_run else []
    if action_sha:
        steps.insert(
            0 if upload_first else len(steps),
            _installer_upload_step(action_sha, upload_condition),
        )
    path.write_text(
        "name: CI\njobs:\n  installer:\n    steps:\n" + "".join(steps),
        encoding="utf-8",
    )


def test_ci_gap_platform_buckets_reject_union_masking_mutation(tmp_path: Path) -> None:
    """Complementary platform workflows must not combine into a false green."""
    mod = load_ci_gap_audit()
    github = tmp_path / ".github" / "workflows"
    gitea = tmp_path / ".gitea" / "workflows"
    github.mkdir(parents=True)
    gitea.mkdir(parents=True)
    (github / "ci.yml").write_text(
        """
name: GitHub CI
jobs:
  checks:
    steps:
      - run: python scripts/release_audit.py
      - run: python -m pytest tests -q -ra --tb=short -p no:cacheprovider
      - run: python -m pytest -q packaging/tests -p no:cacheprovider
      - run: powershell -NoProfile -File packaging/build_inno_installer.ps1 -CheckSourceInputsOnly
      - run: pwsh -NoProfile -File packaging/build_inno_installer.ps1 -CheckSourceInputsOnly
      - run: powershell -NoProfile -File scripts/build_backend_exe.ps1 -Clean
      - run: python scripts/postgres_backup_drill.py
      - run: python scripts/check_api_contract.py
      - run: ruff check app scripts tests packaging/tests
      - run: python -m compileall app scripts tests packaging/tests
      - run: python -m compileall backend_manager tests
      - run: ruff check backend_manager tests
      - run: python -m pytest -q
""",
        encoding="utf-8",
    )
    (gitea / "windows-ci.yml").write_text(
        """
name: Gitea CI
jobs:
  checks:
    steps:
      - run: python scripts/smoke_test.py
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands([github, gitea])

    assert mod._missing_ci_invocations(commands) == []
    platform_missing = mod._missing_ci_invocations_by_platform(commands)
    assert "GitHub: end-to-end smoke" in platform_missing
    assert "GitHub: authoritative Inno installer compile" in platform_missing
    assert "Gitea: release audit aggregator" in platform_missing
    assert "Gitea: installer source preflight (Windows PowerShell 5.1)" in platform_missing
    assert "Gitea: installer source preflight (PowerShell 7)" in platform_missing
    assert "Gitea: frozen backend locked release build" in platform_missing


def test_gitea_platform_requires_connected_android_lane() -> None:
    mod = load_ci_gap_audit()
    command = mod.WorkflowCommand(
        Path("C:/.gitea/workflows/windows-ci.yml"),
        ".\\gradlew.bat --no-daemon --max-workers=2 "
        ":app:testGrayDebugUnitTest :app:assertAndroidTestCountEqualsBaseline "
        ":app:lintGrayDebug :app:detektGrayDebug :app:detektGrayDebugUnitTest "
        ":app:assembleGrayDebug :app:assembleInternalDebug "
        ":app:assembleGrayRelease :app:assembleInternalRelease "
        ":app:kspGrayDebugKotlin --rerun-tasks",
        shell="powershell",
    )

    assert "Gitea: :app:connectedGrayDebugAndroidTest" in (
        mod._missing_gradle_tasks_by_platform([command])
    )


def test_ci_gap_wrapped_output_cannot_satisfy_backend_pins(tmp_path: Path) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: CI
jobs:
  backend:
    steps:
      - run: |
          powershell -Command Write-Host python scripts\\release_audit.py
          powershell -Command Write-Host python scripts\\smoke_test.py
          powershell -Command Write-Host python scripts\\postgres_backup_drill.py
          powershell -Command Write-Host python scripts\\check_api_contract.py
          powershell -Command Write-Host ruff check app scripts tests packaging\\tests
          powershell -Command Write-Host python -m compileall app scripts tests packaging\\tests
""",
        encoding="utf-8",
    )

    missing = mod._missing_ci_invocations(mod._iter_workflow_run_commands(workflows))

    assert "release audit aggregator" in missing
    assert "end-to-end smoke" in missing
    assert "backup/restore drill" in missing
    assert "API contract check" in missing
    assert "backend ruff lint" in missing
    assert "backend compileall" in missing

    business = "python -m pytest tests -q -ra --tb=short -p no:cacheprovider"
    for masked in (
        f"{business} || true",
        f"{business}; cmd /c exit 0",
        f"{business} | Write-Output",
        f"{business}\ncmd /c exit 0",
    ):
        candidate = mod.WorkflowCommand(Path("ci.yml"), masked)
        assert "pytest business full-suite lane" in mod._missing_ci_invocations([candidate])


@pytest.mark.parametrize("platform", ["GitHub", "Gitea"])
def test_authoritative_inno_matcher_rejects_powershell_wrapper_mutations(
    platform: str,
) -> None:
    mod = load_ci_gap_audit()
    matcher = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform][0]
    real = (
        "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass "
        "-File packaging\\build_inno_installer.ps1"
    )

    assert matcher.matches(real)
    for wrapper in (
        "-Command Write-Host",
        "-c Write-Output",
        "-EncodedCommand ZgBhAGsAZQA=",
        "-enc ZgBhAGsAZQA=",
        "-e ZgBhAGsAZQA=",
    ):
        mutated = real.replace("-File", f"{wrapper} -File")
        assert not matcher.matches(mutated), wrapper
    assert not matcher.matches(f"{real} -VerifyOnly")
    for probe in (
        "-VersionContractProbe 1.2.3",
        "-VersionFloorContractProbe 1.2.3|||false",
        "-VersionPolicyContractProbe postgres|17.10",
    ):
        assert not matcher.matches(f"{real} {probe}"), probe

    verifier = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform][1]
    verify = f"{real} -VerifyOnly"
    assert verifier.matches(verify)
    assert not verifier.matches(real)
    assert not verifier.matches(real.replace("-File", "-Command Write-Host -File") + " -VerifyOnly")
    assert not verifier.matches(f"{verify} -VersionContractProbe 1.2.3")


@pytest.mark.parametrize("platform_dir", [".github", ".gitea"])
def test_inno_build_pins_reject_non_executable_and_non_propagating_mutations(
    tmp_path: Path,
    platform_dir: str,
) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / platform_dir / "workflows"
    workflows.mkdir(parents=True)
    compile_command = (
        "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass "
        "-File packaging\\build_inno_installer.ps1"
    )
    verify_command = f"{compile_command} -VerifyOnly"
    mutations = {
        "comment": f"# {compile_command}\n# {verify_command}",
        "prose": (
            f'echo "{compile_command}"\n'
            f'echo "{verify_command}"'
        ),
        "write-host": (
            f'Write-Host "{compile_command}"\n'
            f'Write-Host "{verify_command}"'
        ),
        "wrapped": (
            f"{compile_command.replace('-File', '-Command Write-Host -File')}\n"
            f"{verify_command.replace('-File', '-EncodedCommand ZgBhAGsAZQA= -File')}"
        ),
        "swallowed": (
            f"{compile_command}\n"
            "if ($LASTEXITCODE -ne 0) { exit 0 }\n"
            f"{verify_command} || true"
        ),
    }
    steps = []
    for name, body in mutations.items():
        indented = "\n".join(f"          {line}" for line in body.splitlines())
        steps.append(f"      - name: {name}\n        run: |\n{indented}")
    steps.append(
        "      - name: disabled\n"
        "        if: false\n"
        "        run: |\n"
        f"          {compile_command}\n"
        "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        f"          {verify_command}\n"
        "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
    )
    steps.append(
        "      - name: ignored failure\n"
        "        run: |\n"
        f"          {compile_command}\n"
        "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        f"          {verify_command}\n"
        "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        "        continue-on-error: true"
    )
    steps.append(
        "      - name: disabled after command\n"
        "        run: |\n"
        f"          {compile_command}\n"
        "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        f"          {verify_command}\n"
        "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        "        if: false"
    )
    (workflows / "ci.yml").write_text(
        "name: CI\njobs:\n  installer:\n    steps:\n" + "\n".join(steps) + "\n",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows)
    segments = mod._iter_executable_command_segments(commands)
    platform = "GitHub" if platform_dir == ".github" else "Gitea"
    compile_matcher, verify_matcher = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[
        platform
    ]

    assert not any(compile_matcher.matches(segment) for segment in segments)
    assert not any(verify_matcher.matches(segment) for segment in segments)


@pytest.mark.parametrize("platform_dir", [".github", ".gitea"])
def test_inno_build_pins_accept_direct_commands_with_failure_guards(
    tmp_path: Path,
    platform_dir: str,
) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / platform_dir / "workflows"
    workflows.mkdir(parents=True)
    workflow_path = workflows / "ci.yml"
    _write_installer_workflow(workflow_path)

    commands = mod._iter_workflow_run_commands(workflows)
    segments = mod._iter_executable_command_segments(commands)
    actions = mod._iter_workflow_actions(workflows)
    platform = "GitHub" if platform_dir == ".github" else "Gitea"
    compile_matcher, verify_matcher = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[
        platform
    ]

    assert any(compile_matcher.matches(segment) for segment in segments)
    assert any(verify_matcher.matches(segment) for segment in segments)
    upload_label = f"{platform}: atomic installer publish-unit artifact upload"
    assert upload_label in mod._missing_installer_publish_actions_by_platform(
        commands, actions
    )

    action_sha = (
        "ea165f8d65b6e75b540449e92b4886f43607fa02"
        if platform_dir == ".github"
        else "a8a3f3ad30e3422c9c7b888a15615d19a852ae32"
    )
    _write_installer_workflow(
        workflows / "detached-upload.yml",
        action_sha=action_sha,
        include_run=False,
    )
    actions = mod._iter_workflow_actions(workflows)
    assert upload_label in mod._missing_installer_publish_actions_by_platform(
        commands, actions
    )

    (workflows / "detached-upload.yml").unlink()
    for mutation in (
        {"upload_first": True},
        {"verify_first": True},
        {"upload_condition": "always()"},
        {"upload_condition": "success() || github.event_name == 'pull_request'"},
    ):
        _write_installer_workflow(workflow_path, action_sha=action_sha, **mutation)
        commands = mod._iter_workflow_run_commands(workflows)
        actions = mod._iter_workflow_actions(workflows)
        assert upload_label in mod._missing_installer_publish_actions_by_platform(
            commands, actions
        )

    _write_installer_workflow(workflow_path, action_sha=action_sha)
    commands = mod._iter_workflow_run_commands(workflows)
    actions = mod._iter_workflow_actions(workflows)
    assert upload_label not in mod._missing_installer_publish_actions_by_platform(
        commands, actions
    )
    unknown_commands = [replace(command, step_index=-1) for command in commands]
    assert upload_label in mod._missing_installer_publish_actions_by_platform(
        unknown_commands, actions
    )
    unknown_actions = [replace(action, step_index=-1) for action in actions]
    assert upload_label in mod._missing_installer_publish_actions_by_platform(
        commands, unknown_actions
    )

    _write_installer_workflow(
        workflows / "duplicate-upload.yml",
        action_sha=action_sha,
        include_run=False,
    )
    actions = mod._iter_workflow_actions(workflows)
    assert upload_label in mod._missing_installer_publish_actions_by_platform(
        commands, actions
    )
