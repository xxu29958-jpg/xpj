from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from _local_test_postgres_runtime import (
    _open_exact_windows_process,
    _terminate_exact_windows_process,
    _windows_process_handle_is_running,
)
from _powershell_contract import powershell_contract_engines

from scripts.test_pg_windows_contract import (
    _windows_process_created_filetime,
    _windows_process_kernel32,
)

pytestmark = pytest.mark.packaging_resource("windows_host")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows emulator lifecycle")
def test_emulator_cleanup_requires_exact_process_generation(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    cleanup = project_root / "android" / "scripts" / "stop_ci_emulator.ps1"
    fake_adb = tmp_path / "adb.cmd"
    fake_adb.write_text(
        "@echo off\r\n"
        "if \"%1\"==\"devices\" (\r\n"
        "  echo List of devices attached\r\n"
        "  exit /b 0\r\n"
        ")\r\n"
        "exit /b 1\r\n",
        encoding="ascii",
    )

    for engine in powershell_contract_engines():
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        kernel32 = _windows_process_kernel32()
        exact_kernel32: object | None = None
        exact_handle: object | None = None
        try:
            created = _windows_process_created_filetime(
                kernel32,
                int(child._handle),  # noqa: SLF001
            )
            exact_kernel32, exact_handle = _open_exact_windows_process(
                child.pid,
                created,
            )
            wrong_generation = subprocess.run(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(cleanup),
                    "-AdbPath",
                    str(fake_adb),
                    "-AvdName",
                    "ticketbox_api36_host",
                    "-ProcessId",
                    str(child.pid),
                    "-ProcessStartFileTimeUtc",
                    str(created + 1),
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=20,
                check=False,
            )
            assert wrong_generation.returncode != 0
            assert _windows_process_handle_is_running(exact_kernel32, exact_handle)

            exact_generation = subprocess.run(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(cleanup),
                    "-AdbPath",
                    str(fake_adb),
                    "-AvdName",
                    "ticketbox_api36_host",
                    "-ProcessId",
                    str(child.pid),
                    "-ProcessStartFileTimeUtc",
                    str(created),
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=20,
                check=False,
            )
            assert exact_generation.returncode == 0, (
                exact_generation.stdout + exact_generation.stderr
            )
            child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            if exact_kernel32 is not None and exact_handle is not None:
                _terminate_exact_windows_process(exact_kernel32, exact_handle)
                exact_kernel32.CloseHandle(exact_handle)
