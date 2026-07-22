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
      - .gitea/workflows/android-connected.yml
"""


def _scoped_workflow() -> str:
    return """
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
      desktop: ${{ steps.scope.outputs.desktop }}
      android: ${{ steps.scope.outputs.android }}
      windows: ${{ steps.scope.outputs.windows }}
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10
        with:
          fetch-depth: 0
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.11"
      - id: scope
        shell: bash
        run: |
          python -E -S backend/scripts/ci_scope.py \
            --event "${{ github.event_name }}" \
            --base "${{ github.event.pull_request.base.sha || '' }}" \
            --head "${{ github.event.pull_request.head.sha || github.sha }}" \
            --output "$GITHUB_OUTPUT"
  backend_contracts:
    steps:
      - run: python scripts/release_audit.py
  windows_packaging:
    needs: scope
    if: ${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.windows != 'false') }}
    steps:
      - run: python -m pytest packaging/tests -q
  backend:
    name: Backend
    needs:
      - scope
      - backend_contracts
      - windows_packaging
    if: ${{ always() }}
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Enforce required CI results
        shell: bash
        env:
          SCOPE_RESULT: ${{ needs.scope.result }}
          BACKEND_CONTRACTS_RESULT: ${{ needs.backend_contracts.result }}
          WINDOWS_PACKAGING_RESULT: ${{ needs.windows_packaging.result }}
        run: |
          if [ "$SCOPE_RESULT" != "success" ]; then
            echo "::error::CI scope resolution did not succeed: $SCOPE_RESULT"
            exit 1
          fi
          if [ "$BACKEND_CONTRACTS_RESULT" != "success" ]; then
            echo "::error::Backend contracts did not succeed: $BACKEND_CONTRACTS_RESULT"
            exit 1
          fi
          case "$WINDOWS_PACKAGING_RESULT" in
            success|skipped) ;;
            *)
              echo "::error::Windows release packaging did not succeed: $WINDOWS_PACKAGING_RESULT"
              exit 1
              ;;
          esac
          echo "Required Backend CI results are valid."
  backend-postgres:
    needs: scope
    if: ${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.postgres != 'false') }}
    steps:
      - run: python -m pytest tests -q -ra --tb=short -p no:cacheprovider
"""


def test_fail_closed_scope_job_can_protect_a_heavy_lane(tmp_path: Path) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    workflow = workflows / "ci.yml"
    valid = _scoped_workflow()
    workflow.write_text(valid, encoding="utf-8")

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
    postgres = [command for command in commands if command.job == "backend-postgres"]

    assert len(postgres) == 1
    assert postgres[0].protection_scope == "postgres"

    mutations = (
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
            '          echo "Required Backend CI results are valid."',
            "          exit 0\n          exit 1",
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
            "      - name: Enforce required CI results\n        shell: bash",
            "      - name: Enforce required CI results\n        shell: bash\n"
            "        working-directory: backend",
        ),
    )
    for index, mutated in enumerate(mutations):
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
