from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from _local_test_postgres_runtime import TEST_POSTGRES_CONTRACT
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.packaging_resource("windows_fs")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows protected passfile")
def test_passfile_delete_contention_fails_closed(tmp_path: Path) -> None:
    probe = tmp_path / "passfile-delete-contention.ps1"
    probe.write_text(
        "param($Contract,$DataDirectory)\n"
        ". $Contract\n"
        "[void][IO.Directory]::CreateDirectory($DataDirectory)\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDirectory\n"
        "$passFile = New-XpjTestPostgresPgPassFile "
        "-DataDirectory $DataDirectory -Port 5544 -Credential ('c' * 43)\n"
        "$blocker = [IO.File]::Open($passFile,[IO.FileMode]::Open,"
        "[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)\n"
        "try {\n"
        "  $rejected = $false\n"
        "  try { Remove-XpjTestPostgresPgPassFile "
        "-DataDirectory $DataDirectory -Path $passFile } catch { $rejected = $true }\n"
        "  if (-not $rejected) { throw 'passfile deletion contention was ignored' }\n"
        "  if (-not (Test-Path -LiteralPath $passFile -PathType Leaf)) { "
        "throw 'contended passfile disappeared unexpectedly' }\n"
        "}\n"
        "finally { $blocker.Dispose() }\n"
        "Remove-XpjTestPostgresPgPassFile "
        "-DataDirectory $DataDirectory -Path $passFile\n"
        "if (Test-Path -LiteralPath $passFile) { throw 'passfile survived deletion' }\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        data_directory = tmp_path / f"passfile-delete-{index}"
        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-DataDirectory",
                str(data_directory),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
