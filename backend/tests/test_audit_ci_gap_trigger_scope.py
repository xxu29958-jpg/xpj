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
      - android/audit/test_count_baseline.txt
      - .gitea/workflows/android-connected.yml
"""


_SCOPED_WORKFLOW = """
on:
  pull_request:
    branches: [main]
jobs:
  scope:
    name: CI scope
    runs-on: ubuntu-latest
    timeout-minutes: 5
    outputs:
      postgres: ${{ steps.scope.outputs.postgres }}
      backend_frozen: ${{ steps.scope.outputs.backend_frozen }}
      desktop: ${{ steps.scope.outputs.desktop }}
      android: ${{ steps.scope.outputs.android }}
      windows: ${{ steps.scope.outputs.windows }}
      postgres_matrix: ${{ steps.scope.outputs.postgres_matrix }}
      qualification_sha: ${{ steps.qualification.outputs.sha }}
      qualification_source_sha: ${{ steps.qualification.outputs.source_sha }}
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10
        with:
          fetch-depth: 0
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.11"
      - name: Verify qualification SHA
        id: qualification
        env:
          EXPECTED_SHA: ${{ github.sha }}
          SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
        run: python -E -S backend/scripts/report_qualification_sha.py --expected "$EXPECTED_SHA" --source "$SOURCE_SHA" --output "$GITHUB_OUTPUT"
      - id: scope
        shell: bash
        run: |
          python -E -S backend/scripts/ci_scope.py \
            --event "${{ github.event_name }}" \
            --base "${{ github.event.pull_request.base.sha || '' }}" \
            --head "${{ github.event.pull_request.head.sha || github.sha }}" \
            --output "$GITHUB_OUTPUT"
  backend_contracts:
    outputs:
      qualification_sha: ${{ steps.qualification.outputs.sha }}
      qualification_source_sha: ${{ steps.qualification.outputs.source_sha }}
    steps:
      - run: python scripts/release_audit.py
  backend_frozen:
    needs: scope
    if: ${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.backend_frozen != 'false') }}
    outputs:
      qualification_sha: ${{ steps.qualification.outputs.sha }}
      qualification_source_sha: ${{ steps.qualification.outputs.source_sha }}
    steps:
      - run: powershell -File backend/scripts/build_backend_exe.ps1 -Clean
  windows_packaging:
    needs: scope
    if: ${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.windows != 'false') }}
    outputs:
      qualification_sha: ${{ steps.qualification.outputs.sha }}
      qualification_source_sha: ${{ steps.qualification.outputs.source_sha }}
    steps:
      - run: python -m pytest packaging/tests -q
  backend:
    name: Backend
    needs:
      - scope
      - backend_contracts
      - backend_frozen
      - windows_packaging
    if: ${{ always() }}
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.11"
      - name: Verify qualification SHA
        id: qualification
        env:
          EXPECTED_SHA: ${{ github.sha }}
          SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
        run: python -E -S backend/scripts/report_qualification_sha.py --expected "$EXPECTED_SHA" --source "$SOURCE_SHA" --output "$GITHUB_OUTPUT"
      - name: Enforce required CI results
        env:
          SCOPE_RESULT: ${{ needs.scope.result }}
          BACKEND_FROZEN_SCOPE: ${{ needs.scope.outputs.backend_frozen }}
          WINDOWS_SCOPE: ${{ needs.scope.outputs.windows }}
          BACKEND_CONTRACTS_RESULT: ${{ needs.backend_contracts.result }}
          BACKEND_FROZEN_RESULT: ${{ needs.backend_frozen.result }}
          WINDOWS_PACKAGING_RESULT: ${{ needs.windows_packaging.result }}
          EXPECTED_SHA: ${{ github.sha }}
          EXPECTED_SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
          AGGREGATOR_SHA: ${{ steps.qualification.outputs.sha }}
          AGGREGATOR_SOURCE_SHA: ${{ steps.qualification.outputs.source_sha }}
          SCOPE_SHA: ${{ needs.scope.outputs.qualification_sha }}
          SCOPE_SOURCE_SHA: ${{ needs.scope.outputs.qualification_source_sha }}
          BACKEND_CONTRACTS_SHA: ${{ needs.backend_contracts.outputs.qualification_sha }}
          BACKEND_CONTRACTS_SOURCE_SHA: ${{ needs.backend_contracts.outputs.qualification_source_sha }}
          BACKEND_FROZEN_SHA: ${{ needs.backend_frozen.outputs.qualification_sha }}
          BACKEND_FROZEN_SOURCE_SHA: ${{ needs.backend_frozen.outputs.qualification_source_sha }}
          WINDOWS_PACKAGING_SHA: ${{ needs.windows_packaging.outputs.qualification_sha }}
          WINDOWS_PACKAGING_SOURCE_SHA: ${{ needs.windows_packaging.outputs.qualification_source_sha }}
        run: python -E -S backend/scripts/verify_backend_ci_results.py
  backend-postgres:
    needs: scope
    if: ${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.postgres != 'false') }}
    steps:
      - run: python -m pytest tests -q -ra --tb=short -p no:cacheprovider
"""


def _scope_regressions(valid: str) -> tuple[str, ...]:
    return (
        valid.replace("timeout-minutes: 5", "timeout-minutes: 6", 1),
        valid.replace("fetch-depth: 0", "fetch-depth: 1"),
        valid.replace(
            "if: ${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.postgres != 'false') }}",
            "if: needs.scope.outputs.postgres == 'true'",
        ),
        valid.replace(
            "if: ${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.postgres != 'false') }}",
            "if: env.RUN_POSTGRES == 'true'",
        ),
        valid.replace(
            "postgres: ${{ steps.scope.outputs.postgres }}",
            "postgres: ${{ steps.scope.outputs.android }}",
        ),
        valid.replace(
            "qualification_sha: ${{ steps.qualification.outputs.sha }}",
            "qualification_sha: ${{ steps.scope.outputs.postgres }}",
        ),
        valid.replace("report_qualification_sha.py", "ci_scope.py", 1),
        valid.replace('--expected "$EXPECTED_SHA"', '--expected "${{ github.event.before }}"', 1),
        valid.replace('--output "$GITHUB_OUTPUT"', '--output "$GITHUB_ENV"'),
        valid.replace("python -E -S backend/scripts/ci_scope.py", "python backend/scripts/ci_scope.py"),
        valid.replace(
            "python -E -S backend/scripts/ci_scope.py",
            "# python -E -S backend/scripts/ci_scope.py",
        ),
        valid.replace(
            "python -E -S backend/scripts/ci_scope.py",
            "exit 0\n          python -E -S backend/scripts/ci_scope.py",
        ),
        valid.replace(
            '            --output "$GITHUB_OUTPUT"',
            '            --output "$GITHUB_OUTPUT" || true',
        ),
        valid.replace(
            "run: python -E -S backend/scripts/verify_backend_ci_results.py",
            "run: python -E -S backend/scripts/report_qualification_sha.py",
        ),
        valid.replace(
            "      - scope\n      - backend_contracts",
            "      - backend_contracts",
        ),
        valid.replace(
            "jobs:\n",
            "env:\n  BASH_ENV: backend/scripts/scope-prelude.sh\njobs:\n",
            1,
        ),
        valid.replace(
            "      - id: scope\n        shell: bash",
            "      - id: scope\n        shell: bash\n        env:\n"
            "          BASH_ENV: backend/scripts/scope-prelude.sh",
        ),
        valid.replace(
            "    timeout-minutes: 5\n    outputs:",
            "    timeout-minutes: 5\n    env:\n"
            "      BASH_ENV: backend/scripts/scope-prelude.sh\n    outputs:",
            1,
        ),
        valid.replace(
            "      - name: Enforce required CI results\n        env:",
            "      - name: Enforce required CI results\n"
            "        working-directory: backend\n        env:",
        ),
    )


def test_fail_closed_scope_job_can_protect_a_heavy_lane(tmp_path: Path) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    workflow = workflows / "ci.yml"
    valid = _SCOPED_WORKFLOW
    workflow.write_text(valid, encoding="utf-8")

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
    postgres = [command for command in commands if command.job == "backend-postgres"]

    assert len(postgres) == 1
    assert postgres[0].protection_scope == "postgres"

    extensible = valid.replace(
        "  backend_contracts:\n",
        "      - name: Report resolved scope\n"
        "        run: echo scope-complete\n"
        "  backend_contracts:\n",
        1,
    ).replace(
        "  backend-postgres:\n",
        "      - name: Report required gate\n"
        "        run: echo backend-complete\n"
        "  backend-postgres:\n",
        1,
    )
    workflow.write_text(extensible, encoding="utf-8")
    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
    assert any(
        command.job == "backend-postgres" and command.protection_scope == "postgres"
        for command in commands
    )

    for index, mutated in enumerate(_scope_regressions(valid)):
        assert mutated != valid, index
        workflow.write_text(mutated, encoding="utf-8")
        commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
        assert all(command.job != "backend-postgres" for command in commands), index


def test_windows_scope_protects_real_installer_provenance(tmp_path: Path) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    workflow = workflows / "ci.yml"
    source = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    workflow.write_text(source, encoding="utf-8")

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
    actions = mod._iter_workflow_actions(workflows, protected_only=True)
    hash_label = "GitHub: installer hash output dataflow"
    upload_label = "GitHub: atomic installer publish-unit artifact upload"
    assert hash_label not in mod._missing_installer_hash_dataflow_by_platform(commands)
    assert upload_label not in mod._missing_installer_publish_actions_by_platform(
        commands, actions
    )

    workflow.write_text(
        source.replace(
            "needs.scope.outputs.windows != 'false'",
            "needs.scope.outputs.desktop != 'false'",
            1,
        ),
        encoding="utf-8",
    )
    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
    actions = mod._iter_workflow_actions(workflows, protected_only=True)
    assert hash_label in mod._missing_installer_hash_dataflow_by_platform(commands)
    assert upload_label in mod._missing_installer_publish_actions_by_platform(
        commands, actions
    )


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
