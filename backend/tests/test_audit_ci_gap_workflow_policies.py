from __future__ import annotations

from pathlib import Path

from tests._infra.ci_gap import load_ci_gap_audit as _load
from tests._infra.ci_gap_action_pins import (
    write_action_pin_mutations,
    write_action_pin_workflows,
    write_action_pin_yaml_shapes,
)


def test_github_external_uses_require_exact_commit_sha_across_all_workflows(
    tmp_path: Path,
) -> None:
    mod = _load()
    workflows, mutations = write_action_pin_workflows(tmp_path)
    assert mod._github_external_uses_pin_violations(workflows) == []

    write_action_pin_mutations(workflows, mutations)
    violations = mod._github_external_uses_pin_violations(workflows)
    assert len(violations) == len(mutations)
    for uses in mutations.values():
        assert any(uses in violation for violation in violations)

    write_action_pin_yaml_shapes(workflows)
    shape_violations = mod._github_external_uses_pin_violations(workflows)
    assert any("owner/quoted-action@v1.2.3" in item for item in shape_violations)
    assert any("owner/flow-action@main" in item for item in shape_violations)
    _assert_ci_gap_counts_commands_reachable_on_protected_pull_request(
        tmp_path / "protected-reachable"
    )
    _assert_ci_gap_rejects_workflow_dispatch_only_placement(tmp_path / "manual-only")
    _assert_ci_gap_rejects_powershell_commands_in_unreachable_structures(
        tmp_path / "unreachable-powershell"
    )
    _assert_ci_gap_rejects_false_and_event_excluding_conditions(
        tmp_path / "event-excluded"
    )
    _assert_ci_gap_rejects_conditional_continue_on_error_escape_routes(
        tmp_path / "soft-failure"
    )
    _assert_ci_gap_rejects_script_input_on_non_executing_action(
        tmp_path / "fake-action"
    )
    _assert_ci_gap_requires_proven_protected_conditions(
        tmp_path / "unproven-conditions"
    )
    _assert_ci_gap_stops_at_powershell_terminal_statements(
        tmp_path / "terminal-statements"
    )
    _assert_ci_gap_requires_reachable_needs_graph(tmp_path / "needs-graph")
    _assert_ci_gap_rejects_deferred_powershell_scriptblocks(
        tmp_path / "deferred-scriptblocks"
    )


def _assert_ci_gap_counts_commands_reachable_on_protected_pull_request(
    tmp_path: Path,
) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    workflow = workflows / "ci.yml"
    workflow.write_text(
        """
name: protected PR
on:
  pull_request:
    branches: [main]
  workflow_dispatch:
jobs:
  checks:
    if: ${{ github.event_name == 'pull_request' }}
    continue-on-error: false
    steps:
      - name: required audit
        if: success()
        continue-on-error: false
        run: python scripts/release_audit.py
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    # The command proving reachable also pins the PyYAML YAML-1.1 ``on`` -> bool
    # coercion defense: an uncorrected SafeLoader would produce no events here.
    assert [command.text for command in commands] == ["python scripts/release_audit.py"]


def _assert_ci_gap_rejects_workflow_dispatch_only_placement(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "manual.yml").write_text(
        """
name: manual only
on: workflow_dispatch
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


def _assert_ci_gap_rejects_false_and_event_excluding_conditions(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: excluded commands
on: [pull_request, workflow_dispatch]
jobs:
  manual-job:
    if: github.event_name == 'workflow_dispatch'
    steps:
      - run: python scripts/release_audit.py
  pr-job:
    if: github.event_name == 'pull_request'
    steps:
      - if: false
        run: python scripts/check_api_contract.py
      - if: github.event_name != 'pull_request'
        run: python scripts/smoke_test.py
      - if: ${{ github.event_name == 'pull_request' && false }}
        run: python scripts/postgres_backup_drill.py
      - if: contains(fromJSON('["workflow_dispatch"]'), github.event_name)
        run: python -m compileall app scripts tests packaging/tests
      - if: ${{ !(github.event_name == 'pull_request') }}
        run: ruff check app scripts tests packaging/tests
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert commands == []


def _assert_ci_gap_rejects_conditional_continue_on_error_escape_routes(
    tmp_path: Path,
) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: soft failures
on: pull_request
jobs:
  soft-job:
    continue-on-error: ${{ matrix.experimental }}
    steps:
      - run: python scripts/release_audit.py
  hard-job:
    steps:
      - continue-on-error: true
        run: python scripts/check_api_contract.py
      - continue-on-error: ${{ github.event_name == 'pull_request' }}
        run: python scripts/smoke_test.py
      - continue-on-error: false
        run: python scripts/postgres_backup_drill.py
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert [command.text for command in commands] == [
        "python scripts/postgres_backup_drill.py"
    ]


def _assert_ci_gap_rejects_script_input_on_non_executing_action(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: fake action script
on: pull_request
jobs:
  checks:
    steps:
      - uses: actions/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
        with:
          script: python scripts/release_audit.py
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert commands == []


def _assert_ci_gap_rejects_powershell_commands_in_unreachable_structures(
    tmp_path: Path,
) -> None:
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: unreachable PowerShell gates
on: push
jobs:
  checks:
    defaults:
      run:
        shell: powershell
    steps:
      - run: |
          function Invoke-ReleaseGate {
            python scripts/release_audit.py
          }
          $unusedGate = {
            python scripts/release_audit.py
          }
          if ($true) {
            python scripts/release_audit.py
          }
          if ($false) {
            python scripts/check_api_contract.py
          }
          while ($false) {
            python scripts/smoke_test.py
          }
          for ($i = 0; $false; $i++) {
            python scripts/postgres_backup_drill.py
          }
          foreach ($item in @()) {
            python -m compileall app scripts tests packaging/tests
          }
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert len(commands) == 1
    assert commands[0].text.strip() == ""
    missing = mod._missing_ci_invocations(commands)
    assert "release audit aggregator" in missing
    assert "API contract check" in missing
    assert "end-to-end smoke" in missing
    assert "backup/restore drill" in missing
    assert "backend compileall" in missing


def _assert_ci_gap_requires_proven_protected_conditions(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: proven protected conditions
on: pull_request
jobs:
  checks:
    steps:
      - if: ${{ github.event_name == 'pull_request' }}
        run: python scripts/release_audit.py
      - if: ${{ false && success() }}
        run: python scripts/check_api_contract.py
      - if: ${{ env.RUN_SMOKE == 'true' }}
        run: python scripts/smoke_test.py
      - if: ${{ github.event_name == 'pull_request' && matrix.experimental }}
        run: python scripts/postgres_backup_drill.py
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert [command.text for command in commands] == ["python scripts/release_audit.py"]
    missing = mod._missing_ci_invocations(commands)
    assert "API contract check" in missing
    assert "end-to-end smoke" in missing
    assert "backup/restore drill" in missing


def _assert_ci_gap_stops_at_powershell_terminal_statements(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: terminal PowerShell statements
on: push
jobs:
  checks:
    defaults:
      run:
        shell: powershell
    steps:
      - run: |
          exit 0
          python scripts/release_audit.py
      - run: |
          Write-Output 'done'; return; python scripts/check_api_contract.py
      - run: |
          $payload = @'
          exit 0
          python scripts/smoke_test.py
          '@
          python scripts/postgres_backup_drill.py
      - run: |
          $unused = {
            return
            python -m compileall app scripts tests packaging/tests
          }
          ruff check app scripts tests packaging/tests
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert [command.text.strip() for command in commands] == [
        "exit",
        "Write-Output 'done'\nreturn",
        "python scripts/postgres_backup_drill.py",
        "ruff check app scripts tests packaging/tests",
    ]
    missing = mod._missing_ci_invocations(commands)
    assert "release audit aggregator" in missing
    assert "API contract check" in missing
    assert "end-to-end smoke" in missing
    assert "backend compileall" in missing


def _assert_ci_gap_requires_reachable_needs_graph(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: protected dependency graph
on: pull_request
jobs:
  setup:
    steps:
      - run: echo setup
  reachable:
    needs: setup
    steps:
      - run: python scripts/release_audit.py
  disabled:
    if: false
    steps:
      - run: echo disabled
  skipped-dependent:
    needs: disabled
    steps:
      - run: python scripts/check_api_contract.py
  always-dependent:
    needs: disabled
    if: always()
    steps:
      - run: python scripts/check_api_contract.py
  skipped-transitive:
    needs: skipped-dependent
    steps:
      - run: python scripts/smoke_test.py
  missing-dependent:
    needs: absent
    steps:
      - run: python scripts/postgres_backup_drill.py
  cycle-a:
    needs: cycle-b
    steps:
      - run: python -m compileall app scripts tests packaging/tests
  cycle-b:
    needs: cycle-a
    steps:
      - run: ruff check app scripts tests packaging/tests
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert [command.text for command in commands] == [
        "echo setup",
        "python scripts/release_audit.py",
        "python scripts/check_api_contract.py",
    ]
    missing = mod._missing_ci_invocations(commands)
    assert "release audit aggregator" not in missing
    assert "API contract check" not in missing
    assert "end-to-end smoke" in missing
    assert "backup/restore drill" in missing
    assert "backend compileall" in missing
    assert "backend ruff lint" in missing


def _assert_ci_gap_rejects_deferred_powershell_scriptblocks(tmp_path: Path) -> None:
    mod = _load()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        """
name: deferred PowerShell gates
on: push
jobs:
  checks:
    defaults:
      run:
        shell: powershell
    steps:
      - run: |
          Register-EngineEvent PowerShell.Exiting -Action {
            python scripts/release_audit.py
          }
          Start-Job -ScriptBlock {
            python scripts/check_api_contract.py
          }
          @() | ForEach-Object {
            python scripts/smoke_test.py
          }
      - run: |
          $deferred = [scriptblock] {
            python scripts/check_api_contract.py
            if ($LASTEXITCODE -ne 0) { throw 'deferred gate failed' }
          }
      - run: |
          <#
          python scripts/release_audit.py
          if ($LASTEXITCODE -ne 0) { throw 'commented gate failed' }
          #>
      - run: |
          & {
            python scripts/postgres_backup_drill.py
            if ($LASTEXITCODE -ne 0) { throw 'invoked gate failed' }
          }
      - run: |
          $payload = @'
          prose
            '@
          python -m compileall app scripts tests packaging/tests
""",
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)

    assert len(commands) == 5
    assert [command.text.strip() for command in commands[:3]] == ["", "", ""]
    assert "python scripts/postgres_backup_drill.py" in commands[3].text
    assert commands[4].text.strip() == ""
    missing = mod._missing_ci_invocations(commands)
    assert "release audit aggregator" in missing
    assert "API contract check" in missing
    assert "end-to-end smoke" in missing
    assert "backup/restore drill" not in missing
    assert "backend compileall" in missing
