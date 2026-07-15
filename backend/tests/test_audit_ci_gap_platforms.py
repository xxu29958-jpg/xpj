from dataclasses import replace
from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_gap_audit
from tests._infra.ci_gap_installer import (
    write_installer_workflow as _write_installer_workflow,
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
      - run: python scripts/run_test_lanes.py parallel
      - run: python scripts/run_test_lanes.py stateful
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

    for lane, requirement in (
        ("parallel", "pytest PostgreSQL parallel lane"),
        ("stateful", "pytest stateful serial lane"),
    ):
        business = f"python scripts/run_test_lanes.py {lane}"
        for masked in (
            f"{business} || true",
            f"{business}; cmd /c exit 0",
            f"{business} | Write-Output",
            f"{business}\ncmd /c exit 0",
        ):
            candidate = mod.WorkflowCommand(Path("ci.yml"), masked)
            assert requirement in mod._missing_ci_invocations([candidate])


@pytest.mark.parametrize("platform", ["GitHub", "Gitea"])
def test_authoritative_inno_matcher_rejects_powershell_wrapper_mutations(
    platform: str,
) -> None:
    mod = load_ci_gap_audit()
    matcher = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform][0]
    base = (
        "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass "
        "-File packaging\\build_inno_installer.ps1"
    )
    real = f'{base} -InstallerHashOutputFile "$env:GITHUB_OUTPUT"'

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
    assert not matcher.matches(base)
    assert not matcher.matches(f"{real} -VerifyOnly")
    for probe in (
        "-VersionContractProbe 1.2.3",
        "-VersionFloorContractProbe 1.2.3|||false",
        "-VersionPolicyContractProbe postgres|17.10",
    ):
        assert not matcher.matches(f"{real} {probe}"), probe

    verifier = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform][1]
    verify = f'{base} -VerifyOnly -ExpectedInstallerSha256 "$env:INSTALLER_EXPECTED_SHA256"'
    assert verifier.matches(verify)
    assert not verifier.matches(base)
    assert not verifier.matches(base.replace("-File", "-Command Write-Host -File") + " -VerifyOnly")
    assert not verifier.matches(f"{verify} -VersionContractProbe 1.2.3")


def _write_masked_installer_workflow(workflows: Path) -> None:
    compile_command = (
        "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass "
        "-File packaging\\build_inno_installer.ps1 "
        '-InstallerHashOutputFile "$env:GITHUB_OUTPUT"'
    )
    verify_command = (
        "powershell -NoLogo -NoProfile -ExecutionPolicy Bypass "
        "-File packaging\\build_inno_installer.ps1 "
        '-VerifyOnly -ExpectedInstallerSha256 '
        '"$env:INSTALLER_EXPECTED_SHA256"'
    )
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


@pytest.mark.parametrize("platform_dir", [".github", ".gitea"])
def test_inno_build_pins_reject_non_executable_and_non_propagating_mutations(
    tmp_path: Path,
    platform_dir: str,
) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / platform_dir / "workflows"
    workflows.mkdir(parents=True)
    _write_masked_installer_workflow(workflows)

    commands = mod._iter_workflow_run_commands(workflows)
    segments = mod._iter_executable_command_segments(commands)
    platform = "GitHub" if platform_dir == ".github" else "Gitea"
    compile_matcher, verify_matcher = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[
        platform
    ]

    assert not any(compile_matcher.matches(segment) for segment in segments)
    assert not any(verify_matcher.matches(segment) for segment in segments)


def _assert_upload_order_mutations(
    mod,
    workflows: Path,
    workflow_path: Path,
    action_sha: str,
    upload_label: str,
    commands,
) -> None:
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
        {"download_preparation": "publish_env_override"},
        {"download_preparation": "mixed_case_publish_env_override"},
        {"download_preparation": "rebind_publish_after_resolve"},
        {"download_preparation": "invalid_publish_resolver"},
    ):
        _write_installer_workflow(workflow_path, action_sha=action_sha, **mutation)
        mutated_commands = mod._iter_workflow_run_commands(workflows)
        actions = mod._iter_workflow_actions(workflows)
        assert upload_label in mod._missing_installer_publish_actions_by_platform(
            mutated_commands, actions
        )


def _assert_download_and_unknown_step_mutations(
    mod,
    workflows: Path,
    workflow_path: Path,
    action_sha: str,
    platform: str,
    upload_label: str,
):
    download_label = f"{platform}: uploaded installer publish-unit download"
    for mutation in (
        {"download_first": True},
        {"include_post_upload_verify": False},
    ):
        _write_installer_workflow(workflow_path, action_sha=action_sha, **mutation)
        commands = mod._iter_workflow_run_commands(workflows)
        actions = mod._iter_workflow_actions(workflows)
        missing = mod._missing_installer_publish_actions_by_platform(commands, actions)
        assert upload_label not in missing
        assert download_label in missing
    for preparation in (
        "missing",
        "before_upload",
        "dead_branch",
        "fixed_path",
        "missing_collision_check",
        "missing_create",
        "missing_empty_check",
        "wrong_binding",
        "extra_statement",
        "download_env_override",
        "mixed_case_download_env_override",
        "verify_env_override",
        "mixed_case_verify_env_override",
        "job_env_override",
        "workflow_env_override",
        "rebind_after_prepare",
        "post_verify_inline_hash_override",
    ):
        _write_installer_workflow(
            workflow_path,
            action_sha=action_sha,
            download_preparation=preparation,
        )
        commands = mod._iter_workflow_run_commands(workflows)
        actions = mod._iter_workflow_actions(workflows)
        missing = mod._missing_installer_publish_actions_by_platform(commands, actions)
        assert upload_label not in missing
        assert download_label in missing

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
    return commands


def _assert_duplicate_upload_rejected(
    mod,
    workflows: Path,
    action_sha: str,
    upload_label: str,
    commands,
) -> None:
    _write_installer_workflow(
        workflows / "duplicate-upload.yml",
        action_sha=action_sha,
        include_run=False,
    )
    actions = mod._iter_workflow_actions(workflows)
    assert upload_label in mod._missing_installer_publish_actions_by_platform(
        commands, actions
    )


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
    compile_matcher, verify_matcher = mod.REQUIRED_CI_INVOCATIONS_BY_PLATFORM[platform]
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
    _assert_upload_order_mutations(
        mod, workflows, workflow_path, action_sha, upload_label, commands
    )
    commands = _assert_download_and_unknown_step_mutations(
        mod, workflows, workflow_path, action_sha, platform, upload_label
    )
    _assert_duplicate_upload_rejected(
        mod, workflows, action_sha, upload_label, commands
    )


@pytest.mark.parametrize(
    ("platform_dir", "action_sha"),
    [
        (".github", "ea165f8d65b6e75b540449e92b4886f43607fa02"),
        (".gitea", "a8a3f3ad30e3422c9c7b888a15615d19a852ae32"),
    ],
)
def test_installer_hash_output_dataflow_rejects_detached_mutations(
    tmp_path: Path,
    platform_dir: str,
    action_sha: str,
) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / platform_dir / "workflows"
    workflows.mkdir(parents=True)
    workflow_path = workflows / "ci.yml"
    _write_installer_workflow(workflow_path, action_sha=action_sha)
    platform = "GitHub" if platform_dir == ".github" else "Gitea"
    label = f"{platform}: installer hash output dataflow"
    valid = workflow_path.read_text(encoding="utf-8")

    assert label not in mod._missing_installer_hash_dataflow_by_platform(
        mod._iter_workflow_run_commands(workflows)
    )
    for inline_override in (
        "verify_inline_hash_override",
        "post_verify_inline_hash_override",
    ):
        _write_installer_workflow(
            workflow_path,
            action_sha=action_sha,
            download_preparation=inline_override,
        )
        assert label in mod._missing_installer_hash_dataflow_by_platform(
            mod._iter_workflow_run_commands(workflows)
        )
    _write_installer_workflow(
        workflow_path,
        action_sha=action_sha,
        download_preparation="mixed_case_hash_precedence",
    )
    assert label not in mod._missing_installer_hash_dataflow_by_platform(
        mod._iter_workflow_run_commands(workflows)
    )

    hash_environment = (
        "      - env:\n"
        "          INSTALLER_EXPECTED_SHA256: "
        "${{ steps.compile_installer.outputs.installer_sha256 }}\n"
    )
    compile_output = ' -InstallerHashOutputFile "$env:GITHUB_OUTPUT"'
    failure_guard = "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
    reread_output = (
        "\n          $completion = Get-Content -LiteralPath "
        "dist\\installer\\BUILD_COMPLETE.json -Raw\n"
        "          Add-Content -LiteralPath $env:GITHUB_OUTPUT "
        "-Value \"installer_sha256=$completion\""
    )
    mutations = {
        "missing verifier environment": valid.replace(hash_environment, "", 1),
        "literal verifier hash": valid.replace(
            "${{ steps.compile_installer.outputs.installer_sha256 }}",
            "a" * 64,
            1,
        ),
        "compile omits locked output": valid.replace(compile_output, "", 1),
        "compile rereads mutable completion": valid.replace(
            compile_output,
            reread_output,
            1,
        ),
        "compile output overwritten later": valid.replace(
            failure_guard,
            failure_guard
            + "          Add-Content -LiteralPath $env:GITHUB_OUTPUT "
            + "-Value 'installer_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n",
            1,
        ),
    }
    for mutation, workflow_text in mutations.items():
        workflow_path.write_text(workflow_text, encoding="utf-8")
        missing = mod._missing_installer_hash_dataflow_by_platform(
            mod._iter_workflow_run_commands(workflows)
        )
        assert label in missing, mutation
