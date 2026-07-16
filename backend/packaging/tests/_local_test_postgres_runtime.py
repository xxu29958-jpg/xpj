from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.test_pg_protected_file import write_protected_utf8_file

PROJECT_ROOT = Path(__file__).resolve().parents[3]
START_TEST_POSTGRES = PROJECT_ROOT / "backend" / "scripts" / "start_test_pg.ps1"
STOP_TEST_POSTGRES = PROJECT_ROOT / "backend" / "scripts" / "stop_test_pg.ps1"
TEST_POSTGRES_CONTRACT = PROJECT_ROOT / "backend" / "scripts" / "test_pg_cluster_contract.ps1"
GITEA_RUNNER_CONTRACT = PROJECT_ROOT / "backend" / "scripts" / "assert_gitea_runner_contract.ps1"
STRICT_WINDOWS_RUNTIME_ENV = "XPJ_REQUIRE_WINDOWS_LIFECYCLE_RUNTIME"
TEST_POSTGRES_CREDENTIAL = ".xpj-test-postgres-password"


def _postgres_bin() -> Path:
    candidates: list[Path] = []
    for variable in ("ProgramFiles", "ProgramW6432"):
        raw_root = os.environ.get(variable)
        if not raw_root:
            continue
        for candidate in (Path(raw_root) / "PostgreSQL").glob("*/bin"):
            if all(
                (candidate / executable).is_file()
                for executable in (
                    "initdb.exe",
                    "pg_ctl.exe",
                    "pg_controldata.exe",
                    "postgres.exe",
                    "psql.exe",
                )
            ):
                candidates.append(candidate.resolve())
    if not candidates:
        message = "PostgreSQL runtime is not installed"
        if os.environ.get(STRICT_WINDOWS_RUNTIME_ENV) == "1":
            pytest.fail(message)
        pytest.skip(message)

    def version_key(candidate: Path) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in candidate.parent.name.split("."))
        except ValueError:
            return ()

    return max(candidates, key=version_key)


def _free_local_port() -> int:
    while True:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        if port not in {5432, 5433}:
            return port


def _windows_process_is_running(process_id: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, process_id)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel32.CloseHandle(handle)


def _run_lifecycle(
    engine: str,
    script: Path,
    *,
    port: int,
    data_dir: Path,
    postgres_bin: Path,
    reset_databases: bool = False,
    lifecycle_timeout_seconds: int | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        engine,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Port",
        str(port),
        "-DataDir",
        str(data_dir),
        "-PostgresBin",
        str(postgres_bin),
    ]
    if reset_databases:
        command.append("-ResetDatabases")
    if lifecycle_timeout_seconds is not None:
        command.extend(["-LifecycleMutexTimeoutSeconds", str(lifecycle_timeout_seconds)])
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        env=environment,
    )


def _run_pg(
    postgres_bin: Path,
    executable: str,
    *arguments: str,
    credential_file: Path | None = None,
    port: int | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("PG"):
            environment.pop(key)
    environment["PGREQUIREAUTH"] = "scram-sha-256"
    passfile: Path | None = None
    try:
        if credential_file is None:
            environment["PGPASSFILE"] = str(Path(os.devnull))
        else:
            assert port is not None
            credential = credential_file.read_text(encoding="utf-8").strip()
            assert len(credential) == 43
            passfile = credential_file.parent / (
                f".xpj-pgpass-test-{os.getpid()}-{uuid4().hex}"
            )
            write_protected_utf8_file(
                passfile,
                f"127.0.0.1:{port}:*:postgres:{credential}\n",
                label="Packaging PostgreSQL passfile",
            )
            environment["PGPASSFILE"] = str(passfile)
        return subprocess.run(
            [str(postgres_bin / executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=60,
        )
    finally:
        if passfile is not None:
            passfile.unlink(missing_ok=True)


def _run_lifecycle_contender(
    engine: str,
    contender_script: Path,
    port: int,
    data_directory: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
            "-DataDirectory",
            str(data_directory),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )


def _stop_preserving_data(postgres_bin: Path, data_dir: Path) -> None:
    result = _run_pg(
        postgres_bin,
        "pg_ctl.exe",
        "-D",
        str(data_dir),
        "-m",
        "immediate",
        "-w",
        "-t",
        "30",
        "stop",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _database_exists(
    postgres_bin: Path,
    port: int,
    name: str,
    data_dir: Path,
) -> bool:
    result = _run_pg(
        postgres_bin,
        "psql.exe",
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--username",
        "postgres",
        "--dbname",
        "postgres",
        "--command",
        f"SELECT count(*) FROM pg_database WHERE datname = '{name}'",
        credential_file=data_dir / TEST_POSTGRES_CREDENTIAL,
        port=port,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip() == "1"


def _table_exists(
    postgres_bin: Path,
    port: int,
    database: str,
    table: str,
    data_dir: Path,
) -> bool:
    result = _run_pg(
        postgres_bin,
        "psql.exe",
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--username",
        "postgres",
        "--dbname",
        database,
        "--command",
        f"SELECT to_regclass('public.{table}') IS NOT NULL",
        credential_file=data_dir / TEST_POSTGRES_CREDENTIAL,
        port=port,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip() == "t"
