from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from _local_test_postgres_runtime import (
    START_TEST_POSTGRES,
    STOP_TEST_POSTGRES,
    TEST_POSTGRES_CONTRACT,
    _free_local_port,
    _postgres_bin,
    _run_lifecycle,
)
from _powershell_contract import powershell_contract_engines


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_refuses_an_unowned_existing_directory(
    tmp_path: Path,
) -> None:
    postgres_bin = _postgres_bin()
    data_dir = tmp_path / "unowned"
    data_dir.mkdir()
    sentinel = data_dir / "keep.txt"
    sentinel.write_text("not disposable\n", encoding="ascii")
    port = _free_local_port()

    for engine in powershell_contract_engines():
        result = _run_lifecycle(
            engine,
            START_TEST_POSTGRES,
            port=port,
            data_dir=data_dir,
            postgres_bin=postgres_bin,
        )
        output = result.stdout + result.stderr
        assert result.returncode != 0, f"{engine} accepted an unowned directory"
        assert "ownership marker is missing" in output, output
        assert sentinel.read_text(encoding="ascii") == "not disposable\n"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_test_postgres_lifecycle_mutex_is_cross_process(tmp_path: Path) -> None:
    postgres_bin = _postgres_bin()
    holder_script = tmp_path / "hold-mutex.ps1"
    holder_script.write_text(
        "param($Contract, $Port, $Ready, $Release)\n"
        ". $Contract\n"
        "$mutex = Enter-XpjTestPostgresLifecycleMutex -Port $Port -TimeoutSeconds 5\n"
        "try {\n"
        "  [System.IO.File]::WriteAllText($Ready, [string]$PID)\n"
        "  while (-not (Test-Path -LiteralPath $Release)) { Start-Sleep -Milliseconds 50 }\n"
        "}\n"
        "finally { Exit-XpjTestPostgresLifecycleMutex $mutex }\n",
        encoding="ascii",
    )
    contender_script = tmp_path / "contend-mutex.ps1"
    contender_script.write_text(
        "param($Contract, $Port)\n"
        ". $Contract\n"
        "$mutex = Enter-XpjTestPostgresLifecycleMutex -Port $Port -TimeoutSeconds 1\n"
        "Exit-XpjTestPostgresLifecycleMutex $mutex\n",
        encoding="ascii",
    )

    port = _free_local_port()
    for index, engine in enumerate(powershell_contract_engines()):
        ready = tmp_path / f"mutex-{index}.ready"
        release = tmp_path / f"mutex-{index}.release"
        holder = subprocess.Popen(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(holder_script),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-Port",
                str(port),
                "-Ready",
                str(ready),
                "-Release",
                str(release),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready.exists(), holder.communicate(timeout=2)[0]
            contender = subprocess.run(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(contender_script),
                    "-Contract",
                    str(TEST_POSTGRES_CONTRACT),
                    "-Port",
                    str(port),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            output = contender.stdout + contender.stderr
            assert contender.returncode != 0, output
            assert "Timed out waiting" in output, output

            for lifecycle_script in (START_TEST_POSTGRES, STOP_TEST_POSTGRES):
                entry = _run_lifecycle(
                    engine,
                    lifecycle_script,
                    port=port,
                    data_dir=tmp_path / f"entry-{index}",
                    postgres_bin=postgres_bin,
                    lifecycle_timeout_seconds=1,
                )
                entry_output = entry.stdout + entry.stderr
                assert entry.returncode != 0, entry_output
                assert "Timed out waiting" in entry_output, entry_output

        finally:
            release.write_text("release", encoding="ascii")
            output, _ = holder.communicate(timeout=10)
            assert holder.returncode == 0, output
