import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.xdist_group(name="windows_postgresql_runtime")

PACKAGING = Path(__file__).resolve().parents[1]
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"
PROJECTION_LITERAL = str(PROJECTION.resolve()).replace("'", "''")


def _projection_fixture_command(
    *,
    engine: str,
    fixture: Path,
    pg_bin: Path,
    shawl: Path,
    work_root: Path,
    extra: tuple[str, ...] = (),
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
        "-ContractPath",
        str(PACKAGING / "windows_database_generation_contract.ps1"),
        "-CredentialsPath",
        str(PACKAGING / "windows_postgresql_credentials.ps1"),
        "-RetirementPath",
        str(PACKAGING / "windows_database_generation_retirement.ps1"),
        "-ServiceLifecyclePath",
        str(PACKAGING / "windows_service_lifecycle.ps1"),
        "-SingleUserServicePath",
        str(PACKAGING / "windows_postgresql_single_user.ps1"),
        "-ShawlPath",
        str(shawl),
        "-PgBin",
        str(pg_bin),
        "-SafetyPath",
        str(PACKAGING / "windows_installation_safety.ps1"),
        "-DatabaseSafetyPath",
        str(PACKAGING / "windows_database_safety.ps1"),
        "-DatabaseBindingPath",
        str(PACKAGING / "windows_database_generation_database_binding.ps1"),
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


def _projection_shawl() -> Path | None:
    required = os.environ.get("XPJ_REQUIRE_REAL_PG17_PROJECTION", "")
    assert required in {"", "0", "1"}, "XPJ_REQUIRE_REAL_PG17_PROJECTION must be unset, 0, or 1"
    shawl = PACKAGING / "vendor" / "shawl" / "shawl.exe"
    if shawl.is_file():
        return shawl
    if required == "1":
        pytest.fail("Shawl projection service host is unavailable", pytrace=False)
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


def _assert_parent_timeout_stops_projection_pg(
    *, engine: str, fixture: Path, pg_bin: Path, shawl: Path, tmp_path: Path
) -> None:
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
                shawl=shawl,
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
    shawl = _projection_shawl()
    if pg_bin is None or shawl is None:
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
                        shawl=shawl,
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
    _assert_parent_timeout_stops_projection_pg(
        engine=engines[0], fixture=fixture, pg_bin=pg_bin, shawl=shawl, tmp_path=tmp_path
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows projection contract")
def test_runtime_projection_read_and_retirement_retry_are_fail_closed(tmp_path: Path) -> None:
    harness = tmp_path / "runtime-projection-read.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{PROJECTION_LITERAL}'
$script:writes = 0
$script:mode = 'exact'
$script:adminSecret = New-Object Security.SecureString
$script:adminSecret.AppendChar('a')
$script:adminSecret.MakeReadOnly()
$script:runtimeSecret = New-Object Security.SecureString
$script:runtimeSecret.AppendChar('r')
$script:runtimeSecret.MakeReadOnly()
$script:candidate = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [ordered]@{{
        intent_sha256 = ('a' * 64)
        target_revision = '20260809_0001'
    }}
}}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return $Value | ConvertTo-Json -Compress -Depth 64
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('e' * 64) }}
function Get-TicketboxDatabaseGenerationHostAuthoritySha256 {{ return ('f' * 64) }}
function Read-EnvMap {{
    $map = [Collections.Generic.Dictionary[string,string]]::new()
    if ($script:mode -ceq 'missing') {{ return $map }}
    $map['DATABASE_URL'] = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
    return $map
}}
function Get-TicketboxLocalDatabaseConnection {{
    return [pscustomobject]@{{
        DatabaseUrl = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
        PersistedDatabaseUrl = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
        Password = $script:runtimeSecret
    }}
}}
function Assert-TicketboxConnectedPostgresDataRoot {{}}
function ConvertTo-TicketboxPostgresqlSecureString {{ return $script:runtimeSecret }}
function Test-TicketboxDatabaseGenerationBootstrapRetirement {{ return $script:mode -cne 'foreign' }}
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
    $intent $script:candidate $authority $contract @{{}}
if ($result.PayloadSha256 -cne ('e' * 64) -or $script:writes -ne 0) {{
    throw 'exact runtime projection read mutated state'
}}
foreach ($mode in @('missing', 'foreign')) {{
    $script:mode = $mode
        $rejected = $false
        try {{ Read-TicketboxDatabaseGenerationRuntimeProjection `
            $intent $script:candidate $authority $contract @{{}} | Out-Null }}
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
$script:failAfterMigratorCommit = $true
$script:failFirstEnvWrite = $true
$script:runtimeProjectionWrites = 0
$script:events = @()
$script:adminSecret = New-Object Security.SecureString
$script:adminSecret.AppendChar('a')
$script:adminSecret.MakeReadOnly()
$script:runtimeSecret = New-Object Security.SecureString
$script:runtimeSecret.AppendChar('r')
$script:runtimeSecret.MakeReadOnly()
$script:httpSecret = New-Object Security.SecureString
$script:httpSecret.AppendChar('h')
$script:httpSecret.MakeReadOnly()
function Assert-AdminSecret($Password) {{
    if (-not [object]::ReferenceEquals($Password, $script:adminSecret)) {{
        throw 'projection did not use maintenance authority secret'
    }}
}}
function Assert-TicketboxLifecycleOperationLease {{}}
function Assert-TicketboxDatabaseGenerationMaintenanceAuthority {{
    param($Authority)
    Assert-AdminSecret $Authority.Secret
}}
function Invoke-TicketboxC07Sql {{
    param($Authority, $Database, $Role, $Password, $Label, $Sql)
    Assert-AdminSecret $Password
    $script:events += $Label
    if ($Label -ceq 'database generation migrator authority observation') {{
        return $script:migratorState
    }}
    if ($Label -ceq 'database generation migrator retirement') {{
        if ($script:migratorState -ceq 'active' -and $script:failAfterMigratorCommit) {{
            $script:migratorState = 'retired_pending_sessions'
            $script:failAfterMigratorCommit = $false
            throw 'simulated response loss after migrator retirement commit'
        }}
        $script:migratorState = 'retired'
    }}
    if (
        $Label -ceq 'database generation migrator retirement verification' -and
        $script:migratorState -cne 'retired'
    ) {{ throw 'migrator was not retired' }}
    return ''
}}
function Assert-TicketboxC07RuntimeCredential {{
    param($Authority, $Password)
    if (-not [object]::ReferenceEquals($Password, $script:runtimeSecret)) {{
        throw 'projection did not use runtime credential'
    }}
}}
function Assert-TicketboxC07RoleCatalog {{ param($Authority, $Password); Assert-AdminSecret $Password }}
function Assert-TicketboxC07RuntimeAclContract {{ param($Authority, $SuperuserPassword); Assert-AdminSecret $SuperuserPassword }}
function Assert-TicketboxC07RetiredRoleCatalog {{ param($Authority, $Password); Assert-AdminSecret $Password }}
function Get-TicketboxC07MigratorRetirementSql {{ return 'retire' }}
function Get-TicketboxC07MigratorRetirementVerificationSql {{ return 'verify' }}
function Test-TicketboxDatabaseGenerationBootstrapRetirement {{
    param($Intent, $Candidate, $HostAuthority, $RuntimePassword)
    if (-not [object]::ReferenceEquals($RuntimePassword, $script:runtimeSecret)) {{
        throw 'retirement readback did not use runtime credential'
    }}
    $script:events += 'bootstrap retirement readback'
    return $true
}}
function New-TicketboxDatabaseGenerationRuntimeDatabaseUrl {{
    param($HostAuthority, $RuntimePassword)
    if (-not [object]::ReferenceEquals($RuntimePassword, $script:runtimeSecret)) {{
        throw 'database URL did not use runtime credential'
    }}
    return 'postgresql://runtime'
}}
function Invoke-TicketboxWithPlainPostgresqlSecret {{
    param($Secret, $Action)
    if (-not [object]::ReferenceEquals($Secret, $script:httpSecret)) {{
        throw 'environment projection did not use HTTP credential'
    }}
    return & $Action 'http-secret'
}}
function Write-TicketboxDatabaseGenerationRuntimeEnvironment {{
    param($DatabaseUrl, $ProjectionContract, $HttpBootstrapSecret)
    if ($HttpBootstrapSecret -cne 'http-secret') {{ throw 'wrong HTTP secret' }}
    $script:events += 'env write'
    $script:runtimeProjectionWrites += 1
    if ($script:failFirstEnvWrite) {{
        $script:failFirstEnvWrite = $false
        throw 'simulated response loss after environment projection write'
    }}
}}
function Read-EnvMap {{ return @{{ DATABASE_URL = 'postgresql://runtime' }} }}
function Get-TicketboxLocalDatabaseConnection {{
    return [pscustomobject]@{{
        DatabaseUrl = 'postgresql://runtime'
        PersistedDatabaseUrl = 'postgresql://runtime'
        Password = 'runtime-plain'
    }}
}}
function Assert-TicketboxConnectedPostgresDataRoot {{}}
function ConvertTo-TicketboxPostgresqlSecureString {{ return $script:runtimeSecret }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Compress -Depth 20)
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('e' * 64) }}
function Get-TicketboxDatabaseGenerationHostAuthoritySha256 {{ return ('f' * 64) }}
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
$candidate = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        intent_sha256 = ('a' * 64)
        target_revision = '20260809_0001'
    }}
}}
$runtimeCredentials = [pscustomobject]@{{
    RuntimePassword = $script:runtimeSecret
    HttpBootstrapSecret = $script:httpSecret
}}
$hostAuthority = [pscustomobject]@{{ Port = 5432 }}
$maintenanceAuthority = [pscustomobject]@{{ Secret = $script:adminSecret }}
$contract = [pscustomobject]@{{
    env_path = '.env'; psql_path = 'psql.exe'; pg_data = 'pgdata'
    database_tool_timeout_ms = 1000; backend_service_name = 'TicketboxBackend'
}}
$interrupted = $false
try {{
    Prepare-TicketboxDatabaseGenerationRuntimeProjection `
        $intent $candidate $runtimeCredentials $hostAuthority $maintenanceAuthority `
        $contract @{{}} | Out-Null
}}
catch {{ $interrupted = $true }}
if (-not $interrupted -or $script:migratorState -cne 'retired_pending_sessions') {{
    throw 'migrator response-loss boundary was not preserved'
}}
$prepared = Prepare-TicketboxDatabaseGenerationRuntimeProjection `
    $intent $candidate $runtimeCredentials $hostAuthority $maintenanceAuthority `
    $contract @{{}}
if (
    $prepared.Schema -cne 'ticketbox-database-generation-projection-prepared-v1' -or
    $prepared.CandidateSha256 -cne ('c' * 64) -or
    $script:migratorState -cne 'retired' -or $script:runtimeProjectionWrites -ne 0
) {{ throw 'projection preparation did not converge before admission publication' }}
$script:events += 'bootstrap authority retirement'
if (-not (Test-TicketboxDatabaseGenerationBootstrapRetirement `
    $intent $candidate $hostAuthority $runtimeCredentials.RuntimePassword)) {{
    throw 'retirement readback failed'
}}
$publishInterrupted = $false
try {{
    Publish-TicketboxDatabaseGenerationRuntimeProjection `
        $intent $candidate $runtimeCredentials $hostAuthority $contract @{{}} | Out-Null
}}
catch {{ $publishInterrupted = $true }}
if (-not $publishInterrupted -or $script:runtimeProjectionWrites -ne 1) {{
    throw 'runtime projection response-loss boundary was not reached'
}}
$result = Publish-TicketboxDatabaseGenerationRuntimeProjection `
    $intent $candidate $runtimeCredentials $hostAuthority $contract @{{}}
if ($result.PayloadSha256 -cne ('e' * 64) -or $script:runtimeProjectionWrites -ne 2) {{
    throw 'runtime projection retry did not converge'
}}
$retirementIndex = [Array]::IndexOf($script:events, 'bootstrap authority retirement')
$firstProjectionIndex = [Array]::IndexOf($script:events, 'env write')
if ($retirementIndex -lt 0 -or $firstProjectionIndex -le $retirementIndex) {{
    throw 'runtime projection was published before bootstrap retirement'
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
