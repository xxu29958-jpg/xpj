import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"
PROJECTION_LITERAL = str(PROJECTION.resolve()).replace("'", "''")


def _projection_fixture_command(
    *, engine: str, fixture: Path, pg_bin: Path, work_root: Path, extra: tuple[str, ...] = ()
) -> list[str]:
    return [
        engine,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(fixture),
        "-ProjectionPath",
        str(PROJECTION),
        "-PgBin",
        str(pg_bin),
        "-SafetyPath",
        str(PACKAGING / "windows_installation_safety.ps1"),
        "-AdapterPath",
        str(PACKAGING / "windows_database_generation_adapter.ps1"),
        "-DatabasePolicyPath",
        str(PACKAGING / "windows_c07_database.ps1"),
        "-PythonPath",
        sys.executable,
        "-BackendRoot",
        str(PACKAGING.parent),
        "-WorkRoot",
        str(work_root),
        *extra,
    ]


def _projection_pg_bin() -> Path | None:
    required = os.environ.get("XPJ_REQUIRE_REAL_PG17_PROJECTION", "")
    assert required in {"", "0", "1"}, "XPJ_REQUIRE_REAL_PG17_PROJECTION must be unset, 0, or 1"
    vendor = PACKAGING / "vendor" / "pg" / "bin"
    candidates = (vendor,)
    if required != "1":
        candidates += (Path(os.environ.get("PROGRAMFILES", r"C:\\Program Files")) / "PostgreSQL" / "17" / "bin",)
    for candidate in candidates:
        if all((candidate / f"{name}.exe").is_file() for name in ("initdb", "pg_ctl", "psql")):
            return candidate
    if required == "1":
        pytest.fail("PostgreSQL 17 projection toolset is unavailable", pytrace=False)
    return None


def _ensure_projection_pg_stopped(pg_bin: Path, work_root: Path) -> str | None:
    data_dir = work_root / "pgdata"
    if not data_dir.is_dir():
        return None
    pg_ctl = pg_bin / "pg_ctl.exe"
    try:
        status = subprocess.run(
            [pg_ctl, "status", "-D", data_dir],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not inspect projection PostgreSQL at {data_dir}: {exc}"
    if status.returncode != 0:
        return None if status.returncode == 3 else f"unexpected pg_ctl status {status.returncode}"
    try:
        stopped = subprocess.run(
            [pg_ctl, "stop", "-D", data_dir, "-m", "immediate", "-w", "-t", "30"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        return f"timed out stopping projection PostgreSQL at {data_dir}"
    try:
        final_status = subprocess.run(
            [pg_ctl, "status", "-D", data_dir],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not verify projection PostgreSQL cleanup at {data_dir}: {exc}"
    if stopped.returncode != 0 or final_status.returncode != 3:
        return (
            f"projection PostgreSQL remained live at {data_dir}: "
            f"stop={stopped.returncode}, status={final_status.returncode}"
        )
    return None


def _stop_interrupted_projection_fixture(process: subprocess.Popen[str], pg_bin: Path, work_root: Path) -> str | None:
    errors: list[str] = []
    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"could not stop projection fixture parent: {exc}")
    cleanup_error = _ensure_projection_pg_stopped(pg_bin, work_root)
    if cleanup_error:
        errors.append(cleanup_error)
    return "; ".join(errors) or None


def _assert_parent_timeout_stops_projection_pg(*, engine: str, fixture: Path, pg_bin: Path, tmp_path: Path) -> None:
    work_root = tmp_path / "real-pg-parent-timeout"
    ready_path = work_root / "server-ready"
    stdout_path = tmp_path / "real-pg-parent-timeout.stdout"
    stderr_path = tmp_path / "real-pg-parent-timeout.stderr"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        extra = ("-PauseAfterStart", "-ServerReadyPath", str(ready_path))
        process = subprocess.Popen(
            _projection_fixture_command(
                engine=engine,
                fixture=fixture,
                pg_bin=pg_bin,
                work_root=work_root,
                extra=extra,
            ),
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
        deadline = time.monotonic() + 60
        while not ready_path.is_file() and process.poll() is None:
            if time.monotonic() >= deadline:
                cleanup_error = _stop_interrupted_projection_fixture(process, pg_bin, work_root)
                pytest.fail(
                    "projection fixture did not reach the server-ready boundary"
                    + (f": {cleanup_error}" if cleanup_error else ""),
                    pytrace=False,
                )
            time.sleep(0.05)
        assert ready_path.is_file(), stdout_path.read_text(encoding="utf-8", errors="replace") + stderr_path.read_text(
            encoding="utf-8", errors="replace"
        )
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.1)
        cleanup_error = _stop_interrupted_projection_fixture(process, pg_bin, work_root)
    assert cleanup_error is None, cleanup_error
    status = subprocess.run(
        [pg_bin / "pg_ctl.exe", "status", "-D", work_root / "pgdata"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    assert status.returncode == 3, f"unexpected post-cleanup pg_ctl status {status.returncode}"


def _assert_real_pg17_migrator_authority_states(tmp_path: Path) -> None:
    pg_bin = _projection_pg_bin()
    if pg_bin is None:
        return
    fixture = Path(__file__).with_name("powershell_fixtures") / "database_generation_projection_postgres.ps1"
    engines = tuple(powershell_contract_engines())
    for index, engine in enumerate(engines):
        work_root = tmp_path / f"real-pg-{index}"
        stdout_path = tmp_path / f"real-pg-{index}.stdout"
        stderr_path = tmp_path / f"real-pg-{index}.stderr"
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
                result = subprocess.run(
                    _projection_fixture_command(
                        engine=engine,
                        fixture=fixture,
                        pg_bin=pg_bin,
                        work_root=work_root,
                    ),
                    check=False,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    timeout=300,
                )
        except subprocess.TimeoutExpired as exc:
            cleanup_error = _ensure_projection_pg_stopped(pg_bin, work_root)
            if cleanup_error:
                exc.add_note(cleanup_error)
            raise
        cleanup_error = _ensure_projection_pg_stopped(pg_bin, work_root)
        assert result.returncode == 0, (
            stdout_path.read_text(encoding="utf-8", errors="replace")
            + stderr_path.read_text(encoding="utf-8", errors="replace")
            + (f"\n{cleanup_error}" if cleanup_error else "")
        )
        assert cleanup_error is None, cleanup_error
    _assert_parent_timeout_stops_projection_pg(engine=engines[0], fixture=fixture, pg_bin=pg_bin, tmp_path=tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows projection contract")
def test_runtime_projection_read_and_retirement_retry_are_fail_closed(tmp_path: Path) -> None:
    harness = tmp_path / "runtime-projection-read.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{PROJECTION_LITERAL}'
$script:writes = 0
$script:mode = 'exact'
$script:secret = New-Object Security.SecureString
$script:secret.AppendChar('x')
$script:secret.MakeReadOnly()
$script:current = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [ordered]@{{
        intent_sha256 = ('a' * 64)
        committed_revision = '20260809_0001'
    }}
}}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return $Value | ConvertTo-Json -Compress -Depth 64
}}
function Get-TicketboxDatabaseGenerationRuntimeCurrentPath {{ return 'runtime-current.json' }}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    if ($script:mode -ceq 'missing') {{ throw 'runtime CURRENT missing' }}
    $envelope = [ordered]@{{
        schema = 'ticketbox-database-generation-envelope-v1'
        kind = 'current'
        payload_sha256 = [string]$script:current.PayloadSha256
        payload = $script:current.Payload
    }}
    $text = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope
    if ($script:mode -ceq 'foreign') {{ $text = '{{}}' }}
    return [pscustomobject]@{{ Text = $text }}
}}
function Read-EnvMap {{
    $map = [Collections.Generic.Dictionary[string,string]]::new()
    $map['DATABASE_URL'] = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
    return $map
}}
function Get-TicketboxLocalDatabaseConnection {{
    return [pscustomobject]@{{
        DatabaseUrl = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
        PersistedDatabaseUrl = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
        Password = $script:secret
    }}
}}
function Assert-TicketboxConnectedPostgresDataRoot {{}}
function Write-TicketboxDatabaseGenerationRuntimeCurrent {{ $script:writes += 1 }}
$script:TicketboxC07DatabaseName = 'ticketbox'
$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM', 'Administrators')
$script:TicketboxDatabaseGenerationOwnerAccount = 'Administrators'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        target_revision = '20260809_0001'
    }}
}}
$contract = [pscustomobject]@{{
    backend_service_name = 'TicketboxBackend'; env_path = '.env'
    psql_path = 'psql.exe'; pg_data = 'pgdata'; database_tool_timeout_ms = 1000
}}
$authority = [pscustomobject]@{{ Port = 5432 }}
$result = Read-TicketboxDatabaseGenerationRuntimeProjection `
    $intent $script:current $authority $contract @{{}}
if ($result.CurrentSha256 -cne ('c' * 64) -or $script:writes -ne 0) {{
    throw 'exact runtime projection read mutated state'
}}
foreach ($mode in @('missing', 'foreign')) {{
    $script:mode = $mode
    $rejected = $false
    try {{ Read-TicketboxDatabaseGenerationRuntimeProjection `
        $intent $script:current $authority $contract @{{}} | Out-Null }}
    catch {{ $rejected = $true }}
    if (-not $rejected -or $script:writes -ne 0) {{
        throw "$mode runtime CURRENT did not fail closed without a write"
    }}
}}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
    harness = tmp_path / "runtime-projection-retirement-retry.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{PROJECTION_LITERAL}'
$script:migratorState = 'active'
$script:retirementCalls = 0
$script:runtimeAdmissions = 0
$script:runtimeCurrentWrites = 0
$script:runtimeCurrentText = $null
$script:failAfterRetirementCommit = $true
$script:failFirstCurrentWrite = $true
$script:events = @()
$script:secret = New-Object Security.SecureString
$script:secret.AppendChar('x')
$script:secret.MakeReadOnly()
function Assert-TicketboxLifecycleOperationLease {{}}
function Assert-TicketboxC07SuperuserCapability {{}}
function Invoke-TicketboxC07Sql {{
    param($Authority, $Database, $Role, $Password, $Label, $Sql)
    $script:events += $Label
    if ($Label -ceq 'database generation migrator authority observation') {{
        foreach ($requiredCase in @(
            "THEN 'active'",
            "THEN 'retired_pending_sessions'",
            "THEN 'retired'",
            "ELSE 'invalid'"
        )) {{
            if ([string]$Sql -cnotlike "*$requiredCase*") {{
                throw "migrator observation is missing $requiredCase"
            }}
        }}
        return $script:migratorState
    }}
    if ($Label -ceq 'database generation migrator retirement') {{
        $script:retirementCalls += 1
        if ($script:migratorState -ceq 'active' -and $script:failAfterRetirementCommit) {{
            $script:migratorState = 'retired_pending_sessions'
            $script:failAfterRetirementCommit = $false
            throw 'simulated response loss after retirement commit before session termination'
        }}
        $script:migratorState = 'retired'
    }}
    if ($Label -ceq 'database generation runtime admission') {{
        $script:runtimeAdmissions += 1
    }}
    if (
        $Label -ceq 'database generation migrator retirement verification' -and
        $script:migratorState -cne 'retired'
    ) {{
        throw 'migrator was not retired'
    }}
    return ''
}}
function Assert-TicketboxC07RuntimeCredential {{}}
function Assert-TicketboxC07RoleCatalog {{
    if ($script:migratorState -cne 'active') {{ throw 'active catalog rejected retired migrator' }}
}}
function Assert-TicketboxC07RuntimeAclContract {{}}
function New-TicketboxDatabaseGenerationRuntimeDatabaseUrl {{ return 'postgresql://runtime' }}
function Write-TicketboxDatabaseGenerationRuntimeEnvironment {{ $script:events += 'env write' }}
function Read-EnvMap {{ return @{{ DATABASE_URL = 'postgresql://runtime' }} }}
function Get-TicketboxLocalDatabaseConnection {{
    return [pscustomobject]@{{
        DatabaseUrl = 'postgresql://runtime'
        PersistedDatabaseUrl = 'postgresql://runtime'
        Password = $script:secret
    }}
}}
function Assert-TicketboxConnectedPostgresDataRoot {{}}
function Get-TicketboxC07MigratorRetirementSql {{ return 'retire' }}
function Get-TicketboxC07MigratorRetirementVerificationSql {{ return 'verify' }}
function Assert-TicketboxC07RetiredRoleCatalog {{
    if ($script:migratorState -cne 'retired') {{ throw 'retired catalog was not observed' }}
}}
function Get-TicketboxDatabaseGenerationRuntimeCurrentPath {{ return 'runtime-current.json' }}
function Initialize-TicketboxProtectedDirectoryAtomically {{
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Compress -Depth 20)
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param(
        $Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount,
        [switch]$ReplaceExisting
    )
    $script:events += 'runtime CURRENT write'
    if ($null -ne $script:runtimeCurrentText -and -not $ReplaceExisting) {{
        throw 'runtime CURRENT replacement was not authorized'
    }}
    $script:runtimeCurrentText = [string]$Text
    $script:runtimeCurrentWrites += 1
    if ($script:failFirstCurrentWrite) {{
        $script:failFirstCurrentWrite = $false
        throw 'simulated response loss after runtime CURRENT write'
    }}
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    return [pscustomobject]@{{ Text = $script:runtimeCurrentText }}
}}
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM')
$script:TicketboxDatabaseGenerationOwnerAccount = 'SYSTEM'
$script:TicketboxC07DatabaseName = 'ticketbox'
$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        target_revision = '20260809_0001'
    }}
}}
$current = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        intent_sha256 = ('a' * 64)
        committed_revision = '20260809_0001'
    }}
}}
$credentials = [pscustomobject]@{{ RuntimePassword = $script:secret }}
$hostAuthority = [pscustomobject]@{{ Port = 5432 }}
$capability = [pscustomobject]@{{ Secret = $script:secret }}
$contract = [pscustomobject]@{{
    env_path = '.env'; psql_path = 'psql.exe'; pg_data = 'pgdata'
    database_tool_timeout_ms = 1000; backend_service_name = 'TicketboxBackend'
}}
$retirementInterrupted = $false
try {{
    Complete-TicketboxDatabaseGenerationRuntimeProjection `
        $intent $current $credentials $hostAuthority $capability $contract @{{}} | Out-Null
}}
catch {{ $retirementInterrupted = $true }}
if (
    -not $retirementInterrupted -or
    $script:migratorState -cne 'retired_pending_sessions' -or
    $script:runtimeCurrentWrites -ne 0
) {{
    throw 'retirement commit/session termination interruption was not preserved'
}}
$currentWriteInterrupted = $false
$script:events = @()
try {{
    Complete-TicketboxDatabaseGenerationRuntimeProjection `
        $intent $current $credentials $hostAuthority $capability $contract @{{}} | Out-Null
}}
catch {{ $currentWriteInterrupted = $true }}
if (
    -not $currentWriteInterrupted -or
    $script:migratorState -cne 'retired' -or
    $script:runtimeCurrentWrites -ne 1
) {{
    throw 'runtime CURRENT response-loss boundary was not reached'
}}
$expectedRetryEvents = @(
    'database generation migrator authority observation',
    'database generation migrator retirement',
    'database generation migrator retirement verification',
    'database generation runtime admission',
    'env write',
    'database generation migrator retirement verification',
    'runtime CURRENT write'
)
if (($script:events -join '|') -cne ($expectedRetryEvents -join '|')) {{
    throw "retirement retry event order mismatch: $($script:events -join '|')"
}}
$result = Complete-TicketboxDatabaseGenerationRuntimeProjection `
    $intent $current $credentials $hostAuthority $capability $contract @{{}}
if (
    $result.CurrentSha256 -cne ('c' * 64) -or
    $script:migratorState -cne 'retired' -or
    $script:retirementCalls -ne 2 -or
    $script:runtimeCurrentWrites -ne 2
) {{
    throw 'retired projection retry did not converge through exact CURRENT replacement'
}}
$mutationsBeforeInvalid = $script:runtimeAdmissions
foreach ($invalidState in @('invalid', 'foreign', '')) {{
    $script:migratorState = $invalidState
    $invalidRejected = $false
    try {{
        Complete-TicketboxDatabaseGenerationRuntimeProjection `
            $intent $current $credentials $hostAuthority $capability $contract @{{}} | Out-Null
    }}
    catch {{ $invalidRejected = $true }}
    if (
        -not $invalidRejected -or
        $script:runtimeAdmissions -ne $mutationsBeforeInvalid -or
        $script:runtimeCurrentWrites -ne 2
    ) {{
        throw 'invalid migrator authority reached a projection mutation'
    }}
}}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
    _assert_real_pg17_migrator_authority_states(tmp_path)
