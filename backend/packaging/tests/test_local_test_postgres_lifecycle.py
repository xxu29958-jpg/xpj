from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

from app.services.secure_file import hold_protected_file_for_read

pytestmark = pytest.mark.xdist_group(name="windows_postgresql_runtime")

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_START = _BACKEND_ROOT / "scripts" / "start_test_pg.ps1"
_STOP = _BACKEND_ROOT / "scripts" / "stop_test_pg.ps1"
_LIFECYCLE_CONTRACT = _BACKEND_ROOT / "scripts" / "test_pg_storage_contract.ps1"
_PROCESS_CONTRACT = _BACKEND_ROOT / "scripts" / "test_pg_process_contract.ps1"
_AUTH_CONTRACT = _BACKEND_ROOT / "scripts" / "test_pg_auth_contract.ps1"
_POSTGRES_CONTRACT = json.loads(
    (_BACKEND_ROOT / "scripts" / "test_postgres_contract.json").read_text(encoding="utf-8")
)
_RELEASE_CONFIG = json.loads(
    (_BACKEND_ROOT / "packaging" / "windows-release-config.json").read_text(
        encoding="utf-8"
    )
)


def test_local_lifecycle_creates_databases_through_the_shipped_psql_contract() -> None:
    start_source = _START.read_text(encoding="utf-8-sig")
    assert '"$pgbin\\createdb.exe"' not in start_source
    assert 'foreach ($name in @(\'createdb.exe\'' not in (
        _BACKEND_ROOT / "scripts" / "test_pg_ownership_contract.ps1"
    ).read_text(encoding="utf-8-sig")
    psql_create = '''        Invoke-XpjPsqlCommand `
            -PsqlExe "$pgbin\\psql.exe" `
            -Connection $adminConnection `
            -Query "CREATE DATABASE `"$db`" OWNER `"$applicationRole`"" `
            -Label "PostgreSQL database creation for $db"
'''
    assert start_source.count(psql_create) == 1


@pytest.fixture(scope="module")
def protected_test_postgres_root() -> Path:
    if sys.platform != "win32":
        pytest.skip("Windows PostgreSQL lifecycle")
    powershell_51, _powershell_7 = powershell_contract_engines()
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    completed = _run_powershell(
        [
            powershell_51,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f". '{escaped_contract}'; "
                "(Initialize-XpjTestPostgresRuntimeRoot) | ConvertTo-Json -Compress"
            ),
        ]
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    root = Path(json.loads(completed.stdout.strip().splitlines()[-1]))
    assert root.is_dir()
    return root


def _test_data_dir(root: Path, label: str) -> Path:
    return root / f"xpj_pg_{label}_{uuid.uuid4().hex}"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_lifecycle(
    engine: str,
    script: Path,
    *,
    port: int,
    data_dir: Path,
    invoke_from_parent: bool = False,
    environment: dict[str, str] | None = None,
    postgres_bin_override: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    common = [
        engine,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
    ]
    postgres_bin_arguments: list[str] = []
    if script == _START:
        postgres_bin = postgres_bin_override or _postgres_bin(engine)
        postgres_bin_arguments = ["-PostgresBin", str(postgres_bin)]
    if invoke_from_parent:
        escaped_script = str(script).replace("'", "''")
        escaped_data_dir = str(data_dir).replace("'", "''")
        escaped_postgres_bin = ""
        if postgres_bin_arguments:
            escaped_postgres_bin = (
                " -PostgresBin '"
                + postgres_bin_arguments[1].replace("'", "''")
                + "'"
            )
        command = [
            *common,
            "-Command",
            (
                f"& '{escaped_script}' -Port {port} -DataDir '{escaped_data_dir}'"
                f"{escaped_postgres_bin}"
            ),
        ]
    else:
        command = [
            *common,
            "-File",
            str(script),
            "-Port",
            str(port),
            "-DataDir",
            str(data_dir),
            *postgres_bin_arguments,
        ]
    return _run_powershell(command, environment=environment)


def _run_powershell(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    # A Windows background service can inherit redirected pipe handles. Regular
    # files let the parent exit independently while preserving diagnostic text.
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stdout,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr,
    ):
        completed = subprocess.run(
            command,
            check=False,
            stdout=stdout,
            stderr=stderr,
            env=environment,
            timeout=60,
        )
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            stdout.read().lstrip("\ufeff"),
            stderr.read().lstrip("\ufeff"),
        )


def _create_deletion_receipt(
    engine: str,
    *,
    data_dir: Path,
    port: int,
) -> subprocess.CompletedProcess[str]:
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    escaped_data_dir = str(data_dir).replace("'", "''")
    return _run_powershell(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                f". '{escaped_contract}'; "
                f"$ownership = Assert-XpjTestPostgresOwnership "
                f"-DataDir '{escaped_data_dir}'; "
                f"$null = New-XpjTestPostgresDeletionMarker "
                f"-DataDir '{escaped_data_dir}' -Ownership $ownership -Port {port}"
            ),
        ]
    )


def _run_recovery_attempt(
    engine: str,
    *,
    port: int,
    data_dir: Path,
    postgres_bin: Path,
) -> subprocess.CompletedProcess[str]:
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    escaped_start = str(_START).replace("'", "''")
    escaped_stop = str(_STOP).replace("'", "''")
    escaped_data_dir = str(data_dir).replace("'", "''")
    escaped_postgres_bin = str(postgres_bin).replace("'", "''")
    command = (
        f". '{escaped_contract}'; "
        f"$lease = Enter-XpjTestPostgresLifecycleLock -DataDir '{escaped_data_dir}' -Port {port}; "
        "try { "
        f"& '{escaped_stop}' -Port {port} -DataDir '{escaped_data_dir}'; "
        "if ($LASTEXITCODE -ne 0) { throw 'recovery stop failed' }; "
        f"& '{escaped_start}' -Port {port} -DataDir '{escaped_data_dir}' "
        f"-PostgresBin '{escaped_postgres_bin}'; "
        "if ($LASTEXITCODE -ne 0) { throw 'recovery start failed' } "
        "} finally { Exit-XpjTestPostgresLifecycleLock -Mutex $lease }"
    )
    return _run_powershell(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ]
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_postgres_process_and_binary_identity_are_exact(
    protected_test_postgres_root: Path,
) -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "absolute_identity")
    data_dir.mkdir()
    relative_pid_file = data_dir / "postmaster.pid"
    relative_pid_file.write_text(
        f"{os.getpid()}\n.\\relative-data\n1\n{_free_loopback_port()}\n",
        encoding="utf-8",
    )
    escaped_contract = str(_PROCESS_CONTRACT).replace("'", "''")
    escaped_lifecycle_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    escaped_data_dir = str(data_dir).replace("'", "''")
    vendor_bin = _BACKEND_ROOT / "packaging" / "vendor" / "pg" / "bin"
    escaped_vendor_bin = str(vendor_bin).replace("'", "''")
    start_source = _START.read_text(encoding="utf-8-sig")
    exact_binary_binding = """        Assert-XpjRequestedPostgresBinMatchesOwnership `
            -RequestedPostgresBin ([string]$resolvedRequestedPostgresBin) `
            -OwnershipPostgresBin ([string]$ownershipDisposition.PostgresBin)
"""
    assert start_source.count(exact_binary_binding) == 1
    try:
        for engine in (powershell_51, powershell_7):
            common = [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
            ]
            for candidate in (
                "xpj_pg_relative",
                ".\\xpj_pg_relative",
                "\\xpj_pg_relative",
                "C:xpj_pg_relative",
            ):
                rejected = _run_powershell(
                    [
                        *common,
                        (
                            f". '{escaped_contract}'; "
                            "$null = Get-XpjPostgresDataArgument "
                            f"-CommandLine 'postgres.exe -D \"{candidate}\"' "
                            "-ProcessId 42"
                        ),
                    ]
                )
                assert rejected.returncode != 0

            binary_identity = _run_powershell(
                [
                    *common,
                    (
                        f". '{escaped_lifecycle_contract}'; "
                        f"$vendor = '{escaped_vendor_bin}'; "
                        "$programFiles = [Environment]::GetFolderPath("
                        "[Environment+SpecialFolder]::ProgramFiles); "
                        "$other = Join-Path $programFiles 'PostgreSQL\\17\\bin'; "
                        "Assert-XpjRequestedPostgresBinMatchesOwnership "
                        "-RequestedPostgresBin $vendor.ToUpperInvariant() "
                        "-OwnershipPostgresBin $vendor; "
                        "Assert-XpjRequestedPostgresBinMatchesOwnership "
                        "-RequestedPostgresBin '' -OwnershipPostgresBin $vendor; "
                        "$rejected = $false; try { "
                        "Assert-XpjRequestedPostgresBinMatchesOwnership "
                        "-RequestedPostgresBin $vendor -OwnershipPostgresBin $other "
                        "} catch { $rejected = $true }; "
                        "if (-not $rejected) { throw 'unequal trusted roots were accepted' }"
                    ),
                ]
            )
            assert binary_identity.returncode == 0, (
                binary_identity.stdout + binary_identity.stderr
            )

            accepted = _run_powershell(
                [
                    *common,
                    (
                        f". '{escaped_contract}'; "
                        "$absolute = Get-XpjPostgresDataArgument "
                        f"-CommandLine 'postgres.exe -D \"{escaped_data_dir}\"' "
                        "-ProcessId 42; Write-Output $absolute"
                    ),
                ]
            )
            assert accepted.returncode == 0, accepted.stdout + accepted.stderr
            assert accepted.stdout.strip() == str(data_dir)

            rejected_pid = _run_powershell(
                [
                    *common,
                    (
                        f". '{escaped_contract}'; "
                        f"$null = Read-XpjPostmasterIdentityFile "
                        f"-DataDir '{escaped_data_dir}' -Port 0"
                    ),
                ]
            )
            assert rejected_pid.returncode != 0
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_final_ownership_scan_accepts_only_the_exact_vanished_process_error() -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
. '{escaped_contract}'
$process = Start-Process -FilePath 'cmd.exe' -ArgumentList '/d /c ping 127.0.0.1 -n 6 >nul' -PassThru -WindowStyle Hidden
$processId = $process.Id
Stop-Process -Id $processId -Force
$process.WaitForExit()
$process.Close()
$missing = @(Get-XpjFinalOwnershipScanProcessHandle -ProcessId $processId)
if ($missing.Count -ne 0) {{
    throw 'A process that vanished after the CIM snapshot was not treated as absent'
}}
function Get-Process {{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int[]]$Id
    )
    throw [UnauthorizedAccessException]::new('synthetic access denied')
}}
try {{
    $null = Get-XpjFinalOwnershipScanProcessHandle -ProcessId 42
    throw 'The final ownership scan accepted a non-object-not-found failure'
}}
catch {{
    if ($_.Exception -isnot [UnauthorizedAccessException]) {{
        throw
    }}
}}
Write-Output 'final ownership scan race contract passed'
"""
    for engine in (powershell_51, powershell_7):
        completed = _run_powershell(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_stop_resumes_a_protected_deletion_transaction(
    protected_test_postgres_root: Path,
) -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "deletion_resume")
    port = _free_loopback_port()
    postgres_bin = _postgres_bin(powershell_51)
    started = _run_lifecycle(
        powershell_51,
        _START,
        port=port,
        data_dir=data_dir,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    try:
        stopped = subprocess.run(
            [
                str(postgres_bin / "pg_ctl.exe"),
                "stop",
                "-D",
                str(data_dir),
                "-m",
                "fast",
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        receipt = _create_deletion_receipt(
            powershell_7,
            data_dir=data_dir,
            port=port,
        )
        assert receipt.returncode == 0, receipt.stdout + receipt.stderr

        (data_dir / _POSTGRES_CONTRACT["ownership_marker_name"]).unlink()
        resumed = _run_lifecycle(
            powershell_51,
            _STOP,
            port=port,
            data_dir=data_dir,
        )
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert not data_dir.exists()
        assert not Path(
            str(data_dir) + _POSTGRES_CONTRACT["ownership_marker_name"]
        ).exists()
        assert not Path(
            str(data_dir) + _POSTGRES_CONTRACT["deletion_marker_name"]
        ).exists()
    finally:
        if data_dir.exists():
            cleanup = _run_lifecycle(
                powershell_7,
                _STOP,
                port=port,
                data_dir=data_dir,
            )
            assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_stop_rejects_a_replacement_directory_after_deletion_started(
    protected_test_postgres_root: Path,
) -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "deletion_replacement")
    port = _free_loopback_port()
    postgres_bin = _postgres_bin(powershell_51)
    started = _run_lifecycle(
        powershell_51,
        _START,
        port=port,
        data_dir=data_dir,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    try:
        stopped = subprocess.run(
            [
                str(postgres_bin / "pg_ctl.exe"),
                "stop",
                "-D",
                str(data_dir),
                "-m",
                "fast",
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        receipt = _create_deletion_receipt(
            powershell_7,
            data_dir=data_dir,
            port=port,
        )
        assert receipt.returncode == 0, receipt.stdout + receipt.stderr

        shutil.rmtree(data_dir)
        data_dir.mkdir()
        sentinel = data_dir / "replacement-must-survive.txt"
        sentinel.write_text("foreign replacement", encoding="utf-8")
        rejected = _run_lifecycle(
            powershell_51,
            _STOP,
            port=port,
            data_dir=data_dir,
        )
        assert rejected.returncode != 0
        assert "directory entity changed" in rejected.stderr
        assert sentinel.read_text(encoding="utf-8") == "foreign replacement"
    finally:
        if data_dir.exists():
            shutil.rmtree(data_dir)
        cleanup = _run_lifecycle(
            powershell_7,
            _STOP,
            port=port,
            data_dir=data_dir,
        )
        assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr


def _postgres_bin(engine: str) -> Path:
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    vendor_bin = _BACKEND_ROOT / "packaging" / "vendor" / "pg" / "bin"
    preferred = vendor_bin if vendor_bin.is_dir() else None
    escaped_preferred = str(preferred or "").replace("'", "''")
    escaped_vendor_bin = str(vendor_bin).replace("'", "''")
    resolver = (
        f"Assert-XpjPostgresBinaryWithinReleasePolicy -PostgresBin '{escaped_preferred}'"
        if preferred is not None
        else "Find-XpjPostgresBin"
    )
    command = (
        f". '{escaped_contract}'; "
        f"$bin = [string]({resolver}); "
        "$untrustedRootsRejected = $true; "
        "$outside = [IO.Path]::Combine([IO.Path]::GetTempPath(), "
        "'xpj-untrusted-postgres', 'bin'); "
        f"$vendor = '{escaped_vendor_bin}'; "
        "$probes = @($outside, (Join-Path $vendor 'child'), "
        "(Join-Path (Split-Path -Parent (Split-Path -Parent $vendor)) "
        "'pg-shadow\\bin')); "
        "foreach ($probe in $probes) { "
        "try { Resolve-XpjStoredPostgresBinPath -PostgresBin $probe | Out-Null; "
        "$untrustedRootsRejected = $false } catch {} }; "
        "[ordered]@{ "
        "bin = $bin; "
        "version = (Get-XpjPostgresBinaryVersion -PostgresBin $bin).ToString(); "
        "supported = @((Get-XpjSupportedPostgresMajorVersions)); "
        "untrusted_roots_rejected = $untrustedRootsRejected; "
        "program_files = [Environment]::GetFolderPath("
        "[Environment+SpecialFolder]::ProgramFiles) "
        "} | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=30,
    )
    payload = json.loads(completed.stdout.strip())
    postgres_bin = Path(payload["bin"]).resolve()
    program_files = Path(payload["program_files"]).resolve()
    if preferred is None:
        assert postgres_bin.is_relative_to(program_files)
    else:
        assert postgres_bin == preferred.resolve()
    assert (postgres_bin / "pg_ctl.exe").is_file()
    minimum = int(_RELEASE_CONFIG["postgres_version_policy"]["minimum"].split(".")[0])
    maximum = int(
        _RELEASE_CONFIG["postgres_version_policy"]["maximum_exclusive"].split(".")[0]
    )
    assert payload["supported"] == [str(major) for major in range(minimum, maximum)]
    assert payload["untrusted_roots_rejected"] is True
    if preferred is None:
        assert postgres_bin.parent.name in payload["supported"]
    runtime_version = tuple(int(part) for part in payload["version"].split("."))
    minimum_version = tuple(
        int(part)
        for part in _RELEASE_CONFIG["postgres_version_policy"]["minimum"].split(".")
    )
    maximum_version = tuple(
        int(part)
        for part in _RELEASE_CONFIG["postgres_version_policy"][
            "maximum_exclusive"
        ].split(".")
    )
    runtime_version += (0,) * (3 - len(runtime_version))
    minimum_version += (0,) * (3 - len(minimum_version))
    maximum_version += (0,) * (3 - len(maximum_version))
    assert minimum_version <= runtime_version < maximum_version
    return postgres_bin


def _new_pending_provisioning(
    engine: str,
    *,
    data_dir: Path,
    port: int,
    with_bootstrap_password: bool = False,
) -> dict[str, object]:
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    escaped_auth = str(_AUTH_CONTRACT).replace("'", "''")
    escaped_data_dir = str(data_dir).replace("'", "''")
    escaped_postgres_bin = str(_postgres_bin(engine)).replace("'", "''")
    bootstrap = (
        "$null = New-XpjTestPostgresBootstrapPasswordFile "
        "-DataDir $pending.StagingDir -Credential 'temporary-secret'; "
        if with_bootstrap_password
        else ""
    )
    completed = _run_powershell(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f". '{escaped_contract}'; . '{escaped_auth}'; "
                f"$pending = New-XpjTestPostgresProvisioning -DataDir '{escaped_data_dir}' "
                f"-PostgresBin '{escaped_postgres_bin}' -Port {port}; "
                f"{bootstrap}"
                "$pending | ConvertTo-Json -Compress"
            ),
        ]
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _run_admin_sql(
    postgres_bin: Path,
    data_dir: Path,
    port: int,
    statement: str,
) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment["PGPASSFILE"] = str(
        data_dir / _POSTGRES_CONTRACT["passfile_name"]
    )
    connection = (
        f"host=localhost hostaddr=127.0.0.1 port={port} user=postgres "
        "dbname=postgres connect_timeout=5 require_auth=scram-sha-256 sslmode=disable"
    )
    return subprocess.run(
        [
            str(postgres_bin / "psql.exe"),
            f"--dbname={connection}",
            "--no-psqlrc",
            "--no-password",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            statement,
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )


def _run_pg_ctl(
    postgres_bin: Path,
    data_dir: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(postgres_bin / "pg_ctl.exe"),
            *arguments,
            "-D",
            str(data_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _stop_with_listener_probe_suppressed(
    engine: str,
    *,
    postgres_bin: Path,
    data_dir: Path,
    port: int,
) -> subprocess.CompletedProcess[str]:
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    escaped_data_dir = str(data_dir).replace("'", "''")
    escaped_postgres = str(postgres_bin / "postgres.exe").replace("'", "''")
    command = (
        f". '{escaped_contract}'; "
        "function Get-NetTCPConnection { [CmdletBinding()] param([string]$State, [int]$LocalPort); @() }; "
        f"Stop-XpjOwnedPostgresProcess -DataDir '{escaped_data_dir}' "
        f"-Port {port} -PostgresExe '{escaped_postgres}'"
    )
    return _run_powershell(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]
    )


def _assert_scram_contract(postgres_bin: Path, data_dir: Path, port: int) -> None:
    hba_lines = [
        line.strip()
        for line in (data_dir / "pg_hba.conf").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert hba_lines
    assert all(line.split()[3 if line.split()[0] == "local" else 4] == "scram-sha-256" for line in hba_lines)

    passfile = data_dir / _POSTGRES_CONTRACT["passfile_name"]
    credential = data_dir / _POSTGRES_CONTRACT["credential_name"]
    assert passfile.is_file() and credential.is_file()
    with hold_protected_file_for_read(passfile) as held_passfile:
        assert held_passfile == passfile.resolve()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment["PGPASSFILE"] = str(passfile)
    base = (
        f"host=localhost hostaddr=127.0.0.1 port={port} user=postgres "
        "dbname=postgres connect_timeout=5 sslmode=disable"
    )
    accepted = subprocess.run(
        [
            str(postgres_bin / "psql.exe"),
            f"--dbname={base} require_auth=scram-sha-256",
            "--no-psqlrc",
            "--no-password",
            "-tAc",
            "SHOW password_encryption",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert accepted.stdout.strip() == "scram-sha-256"

    application_role = _POSTGRES_CONTRACT["application_role"]
    application = subprocess.run(
        [
            str(postgres_bin / "psql.exe"),
            "--dbname="
            f"host=localhost hostaddr=127.0.0.1 port={port} user={application_role} "
            f"dbname={_POSTGRES_CONTRACT['smoke_database']} connect_timeout=5 "
            "sslmode=disable require_auth=scram-sha-256",
            "--no-psqlrc",
            "--no-password",
            "-tAc",
            "SELECT session_user || '/' || current_user || '/' || current_database()",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert application.returncode == 0, application.stdout + application.stderr
    assert application.stdout.strip() == (
        f"{application_role}/{application_role}/{_POSTGRES_CONTRACT['smoke_database']}"
    )

    for rejected_environment, required_auth in (
        ({key: value for key, value in environment.items() if key != "PGPASSFILE"}, "scram-sha-256"),
        (environment, "none"),
    ):
        rejected = subprocess.run(
            [
                str(postgres_bin / "psql.exe"),
                f"--dbname={base} require_auth={required_auth}",
                "--no-psqlrc",
                "--no-password",
                "-tAc",
                "SELECT 1",
            ],
            env=rejected_environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert rejected.returncode != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_start_rolls_back_an_existing_cluster_after_post_start_validation_fails(
    protected_test_postgres_root: Path,
) -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    postgres_bin = _postgres_bin(powershell_51)
    port = _free_loopback_port()
    data_dir = _test_data_dir(protected_test_postgres_root, "start_rollback")

    try:
        started = _run_lifecycle(
            powershell_51,
            _START,
            port=port,
            data_dir=data_dir,
        )
        assert started.returncode == 0, started.stdout + started.stderr

        conflicting_marker = _run_admin_sql(
            postgres_bin,
            data_dir,
            port,
            (
                f"COMMENT ON DATABASE {_POSTGRES_CONTRACT['base_database']} "
                "IS 'foreign-cluster'"
            ),
        )
        assert conflicting_marker.returncode == 0, (
            conflicting_marker.stdout + conflicting_marker.stderr
        )

        preserved = _run_pg_ctl(postgres_bin, data_dir, "stop", "-m", "fast", "-w")
        assert preserved.returncode == 0, preserved.stdout + preserved.stderr

        rejected = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=data_dir,
        )
        assert rejected.returncode != 0, rejected.stdout + rejected.stderr
        assert "conflicting database marker" in rejected.stderr

        status = _run_pg_ctl(postgres_bin, data_dir, "status")
        assert status.returncode != 0, status.stdout + status.stderr
    finally:
        if data_dir.exists():
            stopped = _run_lifecycle(
                powershell_7,
                _STOP,
                port=port,
                data_dir=data_dir,
            )
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_lifecycle_is_cross_engine_reentrant_and_fail_closed(
    protected_test_postgres_root: Path,
) -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    postgres_bin = _postgres_bin(powershell_51)
    port = _free_loopback_port()
    owned_dir = _test_data_dir(protected_test_postgres_root, "contract_owned")
    foreign_dir = _test_data_dir(protected_test_postgres_root, "contract_foreign")
    reused_pid_owner_dir = _test_data_dir(
        protected_test_postgres_root, "contract_pid_owner"
    )
    reused_pid_owner_port = _free_loopback_port()
    while reused_pid_owner_port == port:
        reused_pid_owner_port = _free_loopback_port()

    try:
        started = _run_lifecycle(
            powershell_51,
            _START,
            port=port,
            data_dir=owned_dir,
            environment={**os.environ, "PGCTLTIMEOUT": "0"},
        )
        assert started.returncode == 0, started.stdout + started.stderr
        _assert_scram_contract(postgres_bin, owned_dir, port)
        rejected_bin_override = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=owned_dir,
            postgres_bin_override=protected_test_postgres_root / "untrusted" / "bin",
        )
        assert rejected_bin_override.returncode != 0, (
            rejected_bin_override.stdout + rejected_bin_override.stderr
        )
        assert "closed test-runtime roots" in rejected_bin_override.stderr
        assert _run_pg_ctl(postgres_bin, owned_dir, "status").returncode == 0
        host_marker = Path(f"{owned_dir}{_POSTGRES_CONTRACT['ownership_marker_name']}")
        data_marker = owned_dir / _POSTGRES_CONTRACT["ownership_marker_name"]
        provisioning_marker = Path(f"{host_marker}.provisioning")
        assert not provisioning_marker.exists()
        assert not list(protected_test_postgres_root.glob(f"{owned_dir.name}.provisioning.*"))
        assert not list(protected_test_postgres_root.glob("*.bootstrap-password"))
        ownership = json.loads(host_marker.read_text(encoding="utf-8-sig"))
        assert ownership["schema_version"] == 2
        assert Path(ownership["postgres_bin"]).resolve() == postgres_bin
        current_ownership_text = host_marker.read_bytes()

        legacy_ownership = {
            key: value for key, value in ownership.items() if key != "postgres_bin"
        }
        legacy_ownership["schema_version"] = 1
        legacy_text = json.dumps(legacy_ownership, separators=(",", ":")) + "\n"
        host_marker.write_bytes(legacy_text.encode("utf-8"))
        data_marker.write_bytes(legacy_text.encode("utf-8"))

        rejected_legacy = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=owned_dir,
        )
        assert rejected_legacy.returncode != 0
        assert "ownership marker schema is invalid" in rejected_legacy.stderr
        assert _run_pg_ctl(postgres_bin, owned_dir, "status").returncode == 0
        assert host_marker.read_bytes() == legacy_text.encode("utf-8")
        assert data_marker.read_bytes() == legacy_text.encode("utf-8")
        host_marker.write_bytes(current_ownership_text)
        data_marker.write_bytes(current_ownership_text)
        restored_current = _run_lifecycle(
            powershell_51, _START, port=port, data_dir=owned_dir
        )
        assert restored_current.returncode == 0, (
            restored_current.stdout + restored_current.stderr
        )

        recovered_attempt = _run_recovery_attempt(
            powershell_7,
            port=port,
            data_dir=owned_dir,
            postgres_bin=postgres_bin,
        )
        assert recovered_attempt.returncode == 0, (
            recovered_attempt.stdout + recovered_attempt.stderr
        )
        assert "Removed data dir" in recovered_attempt.stdout
        assert "Started PostgreSQL" in recovered_attempt.stdout

        reused = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=owned_dir,
            invoke_from_parent=True,
        )
        assert reused.returncode == 0, reused.stdout + reused.stderr
        assert "Reusing PostgreSQL" in reused.stdout
        _assert_scram_contract(postgres_bin, owned_dir, port)

        stopped_before_listener_probe = _stop_with_listener_probe_suppressed(
            powershell_51,
            postgres_bin=postgres_bin,
            data_dir=owned_dir,
            port=port,
        )
        assert stopped_before_listener_probe.returncode == 0, (
            stopped_before_listener_probe.stdout
            + stopped_before_listener_probe.stderr
        )

        restarted = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=owned_dir,
        )
        assert restarted.returncode == 0, restarted.stdout + restarted.stderr

        marker_removed = _run_admin_sql(
            postgres_bin,
            owned_dir,
            port,
            f"COMMENT ON DATABASE {_POSTGRES_CONTRACT['base_database']} IS NULL",
        )
        assert marker_removed.returncode == 0, marker_removed.stdout + marker_removed.stderr
        marker_recovered = _run_lifecycle(
            powershell_51,
            _START,
            port=port,
            data_dir=owned_dir,
        )
        assert marker_recovered.returncode == 0, (
            marker_recovered.stdout + marker_recovered.stderr
        )
        marker_query = _run_admin_sql(
            postgres_bin,
            owned_dir,
            port,
            (
                "SELECT pg_catalog.shobj_description(oid, 'pg_database') "
                "FROM pg_catalog.pg_database WHERE datname="
                f"'{_POSTGRES_CONTRACT['base_database']}'"
            ),
        )
        assert marker_query.returncode == 0, marker_query.stdout + marker_query.stderr
        assert _POSTGRES_CONTRACT["cluster_marker"] in marker_query.stdout

        conflicting_marker = _run_admin_sql(
            postgres_bin,
            owned_dir,
            port,
            (
                f"COMMENT ON DATABASE {_POSTGRES_CONTRACT['base_database']} "
                "IS 'foreign-cluster'"
            ),
        )
        assert conflicting_marker.returncode == 0, (
            conflicting_marker.stdout + conflicting_marker.stderr
        )
        rejected_marker = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=owned_dir,
        )
        assert rejected_marker.returncode != 0
        assert "conflicting database marker" in rejected_marker.stderr
        restored_marker = _run_admin_sql(
            postgres_bin,
            owned_dir,
            port,
            (
                f"COMMENT ON DATABASE {_POSTGRES_CONTRACT['base_database']} "
                f"IS '{_POSTGRES_CONTRACT['cluster_marker']}'"
            ),
        )
        assert restored_marker.returncode == 0, (
            restored_marker.stdout + restored_marker.stderr
        )

        preserved = subprocess.run(
            [
                str(postgres_bin / "pg_ctl.exe"),
                "stop",
                "-D",
                str(owned_dir),
                "-m",
                "fast",
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert preserved.returncode == 0, preserved.stdout + preserved.stderr
        (owned_dir / "postmaster.pid").write_text(
            f"{os.getpid()}\n{owned_dir.resolve()}\n1\n{port}\n",
            encoding="utf-8",
        )

        stale_stopped = _run_lifecycle(
            powershell_7,
            _STOP,
            port=port,
            data_dir=owned_dir,
        )
        assert stale_stopped.returncode == 0, stale_stopped.stdout + stale_stopped.stderr
        assert "Removed stale PostgreSQL identity" in stale_stopped.stdout
        assert not owned_dir.exists()

        recovered = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=owned_dir,
        )
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr

        rejected = _run_lifecycle(
            powershell_51,
            _START,
            port=port,
            data_dir=foreign_dir,
        )
        assert rejected.returncode != 0, rejected.stdout + rejected.stderr
        assert not foreign_dir.exists()

        pid_owner_started = _run_lifecycle(
            powershell_51,
            _START,
            port=reused_pid_owner_port,
            data_dir=reused_pid_owner_dir,
        )
        assert pid_owner_started.returncode == 0, (
            pid_owner_started.stdout + pid_owner_started.stderr
        )
        reused_postmaster_pid = int(
            (reused_pid_owner_dir / "postmaster.pid")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        preserved = subprocess.run(
            [
                str(postgres_bin / "pg_ctl.exe"),
                "stop",
                "-D",
                str(owned_dir),
                "-m",
                "fast",
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert preserved.returncode == 0, preserved.stdout + preserved.stderr
        (owned_dir / "postmaster.pid").write_text(
            f"{reused_postmaster_pid}\n{owned_dir.resolve()}\n1\n{port}\n",
            encoding="utf-8",
        )

        postgres_pid_reuse_stopped = _run_lifecycle(
            powershell_7,
            _STOP,
            port=port,
            data_dir=owned_dir,
        )
        assert postgres_pid_reuse_stopped.returncode == 0, (
            postgres_pid_reuse_stopped.stdout
            + postgres_pid_reuse_stopped.stderr
        )
        assert "Removed stale PostgreSQL identity" in postgres_pid_reuse_stopped.stdout
        assert not owned_dir.exists()
        _assert_scram_contract(
            postgres_bin,
            reused_pid_owner_dir,
            reused_pid_owner_port,
        )
    finally:
        if owned_dir.exists():
            stopped = _run_lifecycle(
                powershell_7,
                _STOP,
                port=port,
                data_dir=owned_dir,
                invoke_from_parent=True,
            )
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        if reused_pid_owner_dir.exists():
            stopped = _run_lifecycle(
                powershell_7,
                _STOP,
                port=reused_pid_owner_port,
                data_dir=reused_pid_owner_dir,
            )
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert not owned_dir.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_lock_serializes_same_data_dir_across_ports(
    protected_test_postgres_root: Path,
) -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "shared_lock")
    first_port = _free_loopback_port()
    second_port = _free_loopback_port()
    while second_port == first_port:
        second_port = _free_loopback_port()
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    escaped_data_dir = str(data_dir).replace("'", "''")
    holder_command = (
        f". '{escaped_contract}'; "
        f"$lease = Enter-XpjTestPostgresLifecycleLock -DataDir '{escaped_data_dir}' "
        f"-Port {first_port}; "
        "try { [Console]::Out.WriteLine('LOCKED'); [Console]::Out.Flush(); "
        "$release = [Console]::In.ReadLine(); "
        "if ($release -cne 'RELEASE') { throw 'invalid lock-holder release handshake' } "
        "} finally { Exit-XpjTestPostgresLifecycleLock -Mutex $lease }"
    )
    contender_command = (
        f". '{escaped_contract}'; "
        f"$lease = Enter-XpjTestPostgresLifecycleLock -DataDir '{escaped_data_dir}' "
        f"-Port {second_port} -TimeoutSeconds 1; "
        "try { throw 'unexpected lock acquisition' } "
        "finally { Exit-XpjTestPostgresLifecycleLock -Mutex $lease }"
    )
    holder = subprocess.Popen(
        [powershell_7, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", holder_command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().decode(
            "utf-8-sig", errors="replace"
        ).strip() == "LOCKED"
        contender = subprocess.run(
            [
                powershell_51,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                contender_command,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=10,
        )
        assert contender.returncode != 0, contender.stdout + contender.stderr
        assert "DataDir" in contender.stderr
    finally:
        stdout_bytes, stderr_bytes = holder.communicate(input=b"RELEASE\n", timeout=10)
        stdout = stdout_bytes.decode("utf-8-sig", errors="replace")
        stderr = stderr_bytes.decode("utf-8-sig", errors="replace")
        assert holder.returncode == 0, stdout + stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_stop_rejects_unowned_temp_directory(
    tmp_path: Path,
    protected_test_postgres_root: Path,
) -> None:
    _powershell_51, powershell_7 = powershell_contract_engines()
    unowned_dir = _test_data_dir(protected_test_postgres_root, "unowned")
    unowned_dir.mkdir()
    sentinel = unowned_dir / "must-survive.txt"
    sentinel.write_text("not an XPJ PostgreSQL cluster", encoding="utf-8")

    rejected = _run_lifecycle(
        powershell_7,
        _STOP,
        port=_free_loopback_port(),
        data_dir=unowned_dir,
    )

    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    assert "host ownership marker" in rejected.stderr
    assert sentinel.read_text(encoding="utf-8") == "not an XPJ PostgreSQL cluster"

    forged_host_marker = Path(
        f"{unowned_dir}{_POSTGRES_CONTRACT['ownership_marker_name']}"
    )
    forged_host_marker.write_text("{}\n", encoding="utf-8")
    forged = _run_lifecycle(
        powershell_7,
        _STOP,
        port=_free_loopback_port(),
        data_dir=unowned_dir,
    )
    assert forged.returncode != 0, forged.stdout + forged.stderr
    assert "ACL" in forged.stderr
    forged_host_marker.unlink()

    outside_dir = tmp_path / "xpj_pg_outside_runtime_root"
    outside_dir.mkdir()
    outside_sentinel = outside_dir / "must-survive.txt"
    outside_sentinel.write_text("outside", encoding="utf-8")
    outside = _run_lifecycle(
        powershell_7,
        _STOP,
        port=_free_loopback_port(),
        data_dir=outside_dir,
    )
    assert outside.returncode != 0, outside.stdout + outside.stderr
    assert "protected runtime root" in outside.stderr
    assert outside_sentinel.read_text(encoding="utf-8") == "outside"
    shutil.rmtree(unowned_dir)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_stop_and_start_reject_replaced_provisioning_directory(
    protected_test_postgres_root: Path,
) -> None:
    _powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "recreated")
    escaped_contract = str(_LIFECYCLE_CONTRACT).replace("'", "''")
    escaped_data_dir = str(data_dir).replace("'", "''")
    escaped_postgres_bin = str(_postgres_bin(powershell_7)).replace("'", "''")
    created = subprocess.run(
        [
            powershell_7,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f". '{escaped_contract}'; "
                f"$owner = New-XpjTestPostgresOwnership -DataDir '{escaped_data_dir}' "
                f"-PostgresBin '{escaped_postgres_bin}'; "
                "$owner.InstanceId.ToString('D')"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=30,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    assert created.stdout.strip()

    data_dir.mkdir()
    sentinel = data_dir / "must-survive.txt"
    sentinel.write_text("replacement directory", encoding="utf-8")

    rejected = _run_lifecycle(
        powershell_7,
        _STOP,
        port=_free_loopback_port(),
        data_dir=data_dir,
    )

    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    assert "data ownership evidence is missing from a non-empty directory" in (
        rejected.stderr
    )
    assert sentinel.read_text(encoding="utf-8") == "replacement directory"

    rejected_start = _run_lifecycle(
        powershell_7,
        _START,
        port=_free_loopback_port(),
        data_dir=data_dir,
    )
    assert rejected_start.returncode != 0, rejected_start.stdout + rejected_start.stderr
    assert "ownership marker is not a plain file" in rejected_start.stderr
    assert sentinel.read_text(encoding="utf-8") == "replacement directory"
    shutil.rmtree(data_dir)
    Path(f"{data_dir}{_POSTGRES_CONTRACT['ownership_marker_name']}").unlink()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_stop_removes_pending_bootstrap_secret(
    protected_test_postgres_root: Path,
) -> None:
    _powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "pending_secret")
    port = _free_loopback_port()
    pending = _new_pending_provisioning(
        powershell_7,
        data_dir=data_dir,
        port=port,
        with_bootstrap_password=True,
    )
    generation_root = Path(str(pending["GenerationRoot"]))
    staging_dir = Path(str(pending["StagingDir"]))
    bootstrap_password = Path(f"{staging_dir}.bootstrap-password")
    provisioning_marker = Path(str(pending["Path"]))
    assert bootstrap_password.is_file()
    assert provisioning_marker.is_file()

    stopped = _run_lifecycle(
        powershell_7,
        _STOP,
        port=port,
        data_dir=data_dir,
    )

    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert not bootstrap_password.exists()
    assert not provisioning_marker.exists()
    assert not generation_root.exists()
    assert not data_dir.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_start_reclaims_a_proven_interrupted_generation(
    protected_test_postgres_root: Path,
) -> None:
    powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "interrupted_staging")
    port = _free_loopback_port()
    pending = _new_pending_provisioning(
        powershell_51,
        data_dir=data_dir,
        port=port,
    )
    generation_root = Path(str(pending["GenerationRoot"]))
    staging_dir = Path(str(pending["StagingDir"]))
    staging_dir.mkdir()
    sentinel = staging_dir / "must-survive.txt"
    sentinel.write_text("unproven staging", encoding="utf-8")

    try:
        started = _run_lifecycle(
            powershell_7,
            _START,
            port=port,
            data_dir=data_dir,
        )
        assert started.returncode == 0, started.stdout + started.stderr
        assert "Removed the proven interrupted PostgreSQL provisioning generation" in (
            started.stdout + started.stderr
        )
        assert not generation_root.exists()
        assert not sentinel.exists()
        assert data_dir.is_dir()
    finally:
        if data_dir.exists():
            stopped = _run_lifecycle(
                powershell_7,
                _STOP,
                port=port,
                data_dir=data_dir,
            )
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_preserves_a_generation_without_birth_evidence(
    protected_test_postgres_root: Path,
) -> None:
    _powershell_51, powershell_7 = powershell_contract_engines()
    data_dir = _test_data_dir(protected_test_postgres_root, "untrusted_generation")
    port = _free_loopback_port()
    pending = _new_pending_provisioning(
        powershell_7,
        data_dir=data_dir,
        port=port,
    )
    generation_root = Path(str(pending["GenerationRoot"]))
    staging_dir = Path(str(pending["StagingDir"]))
    birth_marker = generation_root / ".xpj-test-postgres-provisioning-birth.json"
    birth_marker.unlink()
    staging_dir.mkdir()
    sentinel = staging_dir / "must-survive.txt"
    sentinel.write_text("untrusted replacement", encoding="utf-8")

    rejected = _run_lifecycle(
        powershell_7,
        _START,
        port=port,
        data_dir=data_dir,
    )

    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    assert "lost its birth evidence" in rejected.stderr
    assert sentinel.read_text(encoding="utf-8") == "untrusted replacement"
    assert Path(str(pending["Path"])).is_file()
    shutil.rmtree(staging_dir)
    recovered = _run_lifecycle(
        powershell_7,
        _STOP,
        port=port,
        data_dir=data_dir,
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert not generation_root.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_stop_rejects_prefixed_file(
    protected_test_postgres_root: Path,
) -> None:
    _powershell_51, powershell_7 = powershell_contract_engines()
    unowned_file = _test_data_dir(protected_test_postgres_root, "unowned_file")
    unowned_file.write_text("must survive", encoding="utf-8")

    rejected = _run_lifecycle(
        powershell_7,
        _STOP,
        port=_free_loopback_port(),
        data_dir=unowned_file,
    )

    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    assert unowned_file.read_text(encoding="utf-8") == "must survive"
    unowned_file.unlink()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_stop_rejects_junction_without_touching_target(
    tmp_path: Path,
    protected_test_postgres_root: Path,
) -> None:
    _powershell_51, powershell_7 = powershell_contract_engines()
    target = tmp_path / "foreign-target"
    target.mkdir()
    sentinel = target / "must-survive"
    sentinel.write_text("foreign", encoding="utf-8")
    junction = _test_data_dir(protected_test_postgres_root, "junction")
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    rejected = _run_lifecycle(
        powershell_7,
        _STOP,
        port=_free_loopback_port(),
        data_dir=junction,
    )

    assert rejected.returncode != 0, rejected.stdout + rejected.stderr
    assert sentinel.read_text(encoding="utf-8") == "foreign"
    os.rmdir(junction)
