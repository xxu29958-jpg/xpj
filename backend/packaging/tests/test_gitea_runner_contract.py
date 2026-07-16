from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from _local_test_postgres_runtime import (
    GITEA_RUNNER_CONTRACT,
    PROJECT_ROOT,
)
from _powershell_contract import powershell_contract_engines


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Gitea runner contract")
def test_gitea_runner_minimum_version_is_executable_under_ps51_and_ps7(
    tmp_path: Path,
) -> None:
    old_runner = tmp_path / "gitea-runner-old.cmd"
    old_runner.write_text("@echo gitea-runner version v1.0.8\n", encoding="ascii")
    current_runner = tmp_path / "gitea-runner-current.cmd"
    current_runner.write_text("@echo gitea-runner version v2.0.0\n", encoding="ascii")

    workflow = (PROJECT_ROOT / ".gitea" / "workflows" / "windows-ci.yml").read_text(encoding="utf-8")
    postgres_job = workflow[workflow.index("  backend-postgres:") :]
    assert postgres_job.index("assert_gitea_runner_contract.ps1") < postgres_job.index("Install backend dependencies")

    for engine in powershell_contract_engines():
        base = [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(GITEA_RUNNER_CONTRACT),
            "-RunnerExecutable",
        ]
        rejected = subprocess.run(
            [*base, str(old_runner)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert rejected.returncode != 0
        assert "below required 2.0.0" in (rejected.stdout + rejected.stderr)

        accepted = subprocess.run(
            [*base, str(current_runner)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert "contract OK: 2.0.0" in accepted.stdout
