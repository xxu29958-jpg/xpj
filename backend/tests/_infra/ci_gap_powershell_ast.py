"""Complete-command PowerShell AST mutation scenarios for the CI gap gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_gap_audit

_POWERSHELL_AST_WORKFLOW = """
name: complete PowerShell AST
on: push
jobs:
  checks:
    defaults:
      run:
        shell: powershell
    steps:
      - name: valid top-level catch endings
        run: |
          try {
            ./gradlew --no-daemon :app:assembleGrayRelease
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch [System.InvalidOperationException] {
            Write-Output 'typed catch'
            throw
          } catch {
            throw
          } finally {
            Write-Output 'cleanup'
          }
      - name: same-line catch must not leak a later throw
        run: |
          try {
            ./gradlew --no-daemon :app:assembleInternalRelease
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch [System.InvalidOperationException] { Write-Output 'swallowed' } catch { throw }
      - name: finally exit overrides catch throw
        run: |
          try {
            ./gradlew --no-daemon :app:lintGrayDebug
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch { throw } finally { exit 0 }
      - name: finally return overrides catch throw
        run: |
          try {
            ./gradlew --no-daemon :app:detektGrayDebug
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch { throw } finally { return }
      - name: finally trap can suppress propagation
        run: |
          try {
            ./gradlew --no-daemon :app:assembleInternalDebug
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch { throw } finally { trap { continue } }
      - name: catch exit before throw suppresses propagation
        run: |
          try {
            ./gradlew --no-daemon :app:testGrayDebugUnitTest
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch { exit 0; throw }
      - name: catch return before throw suppresses propagation
        run: |
          try {
            ./gradlew --no-daemon :app:detektGrayDebugUnitTest
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch { return; throw }
      - name: catch loop terminator before throw suppresses propagation
        run: |
          try {
            ./gradlew --no-daemon :app:assembleGrayDebug
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch { break; throw }
      - name: catch trap before throw suppresses propagation
        run: |
          try {
            ./gradlew --no-daemon :app:lintGrayDebug
            if ($LASTEXITCODE -ne 0) { throw 'gradle failed' }
          } catch { trap { continue }; throw }
      - name: top-level trap suppresses propagation
        run: |
          trap { continue }
          ./gradlew --no-daemon :app:lintGrayDebug
"""


def assert_ci_gap_uses_complete_powershell_ast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = load_ci_gap_audit()
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        _POWERSHELL_AST_WORKFLOW,
        encoding="utf-8",
    )

    commands = mod._iter_workflow_run_commands(workflows, protected_only=True)
    missing = mod._missing_gradle_tasks(commands)

    assert commands[0].text.strip()
    assert all(not command.text.strip() for command in commands[1:])
    assert ":app:assembleGrayRelease" not in missing
    assert ":app:assembleInternalRelease" in missing
    assert ":app:lintGrayDebug" in missing
    assert ":app:detektGrayDebug" in missing
    assert ":app:assembleInternalDebug" in missing
    assert ":app:testGrayDebugUnitTest" in missing
    assert ":app:detektGrayDebugUnitTest" in missing
    assert ":app:assembleGrayDebug" in missing

    powershell = sys.modules["ci_gap_powershell"]
    with monkeypatch.context() as context:
        context.setattr(powershell.shutil, "which", lambda _name: None)
        assert not powershell.powershell_ast_propagates_failure(
            "Write-Output 'parser unavailable'"
        )
