import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]
DATABASE_SCRIPT = PACKAGING / "windows_bundled_database.ps1"
INSTALL_SCRIPT = PACKAGING / "install_bundled_services.ps1"
DATABASE_SAFETY_SCRIPT = PACKAGING / "windows_database_safety.ps1"
INSTALLATION_SAFETY_SCRIPT = PACKAGING / "windows_installation_safety.ps1"
PREPARE_SCRIPT = PACKAGING / "prepare_bundled_upgrade.ps1"


def _read_database_script() -> str:
    return DATABASE_SCRIPT.read_text(encoding="utf-8-sig")


def _powershell_engines() -> list[str]:
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    return engines


def _ps_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _write_ps1(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8-sig")


def _run_ps1(engine: str, script: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _build_native_stub(tmp_path: Path) -> Path:
    compiler = shutil.which("powershell")
    if compiler is None:
        pytest.skip("Windows PowerShell 5.1 is required to compile the native test stub")

    source_path = tmp_path / "ticketbox_native_stub.cs"
    output_path = tmp_path / "ticketbox-native-stub.exe"
    source_path.write_text(
        r"""
using System;
using System.IO;
using System.Text;

public static class TicketboxNativeStub
{
    public static int Main(string[] args)
    {
        string executable = Path.GetFileNameWithoutExtension(
            Environment.GetCommandLineArgs()[0]
        ).ToLowerInvariant();
        string tracePath = Environment.GetEnvironmentVariable("TICKETBOX_TEST_ARGV_TRACE");
        if (!String.IsNullOrEmpty(tracePath))
        {
            File.AppendAllText(
                tracePath,
                executable + "|" + String.Join("|", args) + Environment.NewLine,
                Encoding.UTF8
            );
        }

        if (executable == "initdb")
        {
            string dataRoot = null;
            string passwordFile = null;
            for (int index = 0; index < args.Length; index += 1)
            {
                if (args[index] == "-D" && index + 1 < args.Length)
                {
                    dataRoot = args[index + 1];
                }
                if (args[index].StartsWith("--pwfile=", StringComparison.Ordinal))
                {
                    passwordFile = args[index].Substring("--pwfile=".Length);
                }
            }
            if (String.IsNullOrEmpty(dataRoot) || String.IsNullOrEmpty(passwordFile))
            {
                return 21;
            }
            if (!File.Exists(passwordFile))
            {
                return 22;
            }
            using (StreamReader reader = new StreamReader(passwordFile, Encoding.ASCII))
            {
                if (String.IsNullOrEmpty(reader.ReadLine()))
                {
                    return 23;
                }
            }
            Directory.CreateDirectory(dataRoot);
            if (Environment.GetEnvironmentVariable("TICKETBOX_TEST_NATIVE_MODE") == "partial-init-fail")
            {
                File.WriteAllText(
                    Path.Combine(dataRoot, "partial-init.tmp"),
                    "incomplete",
                    Encoding.ASCII
                );
                return 25;
            }
            File.WriteAllText(Path.Combine(dataRoot, "PG_VERSION"), "17", Encoding.ASCII);
            File.WriteAllText(
                Path.Combine(dataRoot, "postgresql.conf"),
                "# native stub" + Environment.NewLine,
                Encoding.ASCII
            );
            return 0;
        }

        if (executable == "psql")
        {
            foreach (string variable in new string[] {
                "PGPASSWORD", "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE",
                "PGUSER", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGREQUIREAUTH"
            })
            {
                if (!String.IsNullOrEmpty(Environment.GetEnvironmentVariable(variable)))
                {
                    return 26;
                }
            }
            string passfile = Environment.GetEnvironmentVariable("PGPASSFILE");
            if (String.IsNullOrEmpty(passfile) || !File.Exists(passfile))
            {
                return 27;
            }
            bool requiresScram = false;
            foreach (string argument in args)
            {
                if (argument.Contains("require_auth=scram-sha-256"))
                {
                    requiresScram = true;
                }
            }
            if (!requiresScram)
            {
                return 28;
            }
            Console.In.ReadToEnd();
            string mode = Environment.GetEnvironmentVariable("TICKETBOX_TEST_NATIVE_MODE");
            if (mode == "stderr")
            {
                Console.Error.Write("native-stderr-secret-sentinel");
                return 9;
            }
            Console.Out.Write("1");
            return 0;
        }
        return 24;
    }
}
""".strip(),
        encoding="utf-8",
    )
    compile_script = tmp_path / "compile-native-stub.ps1"
    _write_ps1(
        compile_script,
        f"""
$ErrorActionPreference = 'Stop'
$source = Get-Content -LiteralPath '{_ps_literal(source_path)}' -Raw -Encoding UTF8
Add-Type -TypeDefinition $source -Language CSharp `
    -OutputAssembly '{_ps_literal(output_path)}' `
    -OutputType ConsoleApplication
""".strip(),
    )
    result = _run_ps1(compiler, compile_script, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output_path.is_file()
    return output_path


def test_bootstrap_recovery_static_contract(tmp_path: Path) -> None:
    database = _read_database_script()
    database_safety = DATABASE_SAFETY_SCRIPT.read_text(encoding="utf-8-sig")

    assert '$script:PostgresBootstrapRecoveryFileName = ".postgres-bootstrap-password"' in database
    assert 'FileMode]::CreateNew' in database
    assert 'FileOptions]::WriteThrough' in database
    assert '$stream.Flush($true)' in database
    assert 'Move-TicketboxFileAtomically -Source $tempPath -Destination $pwfile' in database
    assert 'Set-TicketboxExactFileAcl `' in database
    assert 'Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile' in database
    assert 'Get-OrCreatePostgresBootstrapRecoveryState' in database
    assert '--pwfile=$pwfile' in database
    assert 'ALTER ROLE `"$DbRole`" WITH LOGIN PASSWORD' in database
    assert '既有应用数据库 owner 不是预期角色' in database
    assert '$script:HttpBootstrapSecretByteCount = 32' not in database
    assert '$script:HttpBootstrapSecretEncodedLength = 43' not in database
    assert "$byteCount = [int]$SecretByteCount" in database
    assert "$expectedLength = Get-HttpBootstrapSecretEncodedLength" in database
    assert '"=" * $paddingLength' in database
    assert (
        "$SecretByteCount = [int]$ReleaseConfig.secret_byte_count"
        in INSTALL_SCRIPT.read_text(encoding="utf-8-sig")
    )
    assert "function New-HttpBootstrapSecret" in database
    assert "[Convert]::ToBase64String($bytes)" in database
    assert "HttpBootstrapSecret = New-HttpBootstrapSecret" in database
    assert "HttpBootstrapSecret = New-StrongPassword" not in database
    assert (
        "return Join-Path $AppData $script:PostgresBootstrapRecoveryFileName"
        in database
    )
    assert (
        '$PgBootstrapRecoveryPath = Join-Path $AppData ".postgres-bootstrap-password"'
        in PREPARE_SCRIPT.read_text(encoding="utf-8-sig")
    )
    fresh_write = database.index("[void](Get-OrCreatePostgresBootstrapRecoveryState)")
    initdb = database.index('Join-Path $PgBin "initdb.exe"', fresh_write)
    assert fresh_write < initdb

    existing_cluster = database.index(
        "if (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)"
    )
    recovery_validation = database.index(
        "[void](Read-PostgresBootstrapRecoveryState)", existing_cluster
    )
    config_mutation = database.index(
        "Set-TicketboxPostgresInstallerConfiguration", existing_cluster
    )
    assert recovery_validation < config_mutation

    prepare = database.index("function Prepare-DatabaseIfNeeded")
    env_write = database.index("Write-EnvNoBom -Path $EnvPath", prepare)
    app_connection_check = database.index("Assert-TicketboxConnectedPostgresDataRoot", env_write)
    recovery_cleanup = database.index("Remove-TicketboxSensitiveFile $pwfile", app_connection_check)
    assert env_write < app_connection_check < recovery_cleanup

    assert '"-tAc", $Sql' not in database
    assert '"--dbname", $ProtectedDatabaseUrl, "-tA"' in database
    assert "Invoke-TicketboxBoundedNativeProcess" in database
    assert '-StandardInputText ($Sql + "`n")' in database
    assert "$out = $Sql | & $psql @args 2>&1" not in database
    assert "Invoke-TicketboxWithPgPassFile" in database
    assert '$env:PGPASSWORD = $Password' not in database
    assert 'throw "psql 执行失败（db=$Database, exit=$($result.ExitCode)）。"' in database
    assert '$Sql`n$out' not in database
    assert '$State.SuperuserPassword 2>&1' not in database

    passfile_directory = database_safety[
        database_safety.index(
            "function Get-TicketboxProtectedPgPassDirectory"
        ) : database_safety.index(
            "function New-TicketboxProtectedPgPassFile"
        )
    ]
    assert "LocalApplicationData" in passfile_directory
    assert "CommonProgramFiles" not in passfile_directory
    assert "WindowsPrincipal" not in passfile_directory
    assert "$accounts = @($identity.User.Value)" in passfile_directory
    assert ".ticketbox-protected-*.tmp" in passfile_directory
    passfile_cleanup = database_safety[
        database_safety.index(
            "function Remove-TicketboxProtectedPgPassArtifact"
        ) : database_safety.index(
            "function Get-TicketboxProtectedPgPassDirectory"
        )
    ]
    assert "Read-TicketboxProtectedUtf8Artifact" not in passfile_cleanup
    assert "$item.Length -gt $MaximumBytes" in passfile_cleanup

    passfile_writer = database_safety[
        database_safety.index(
            "function New-TicketboxProtectedPgPassFile"
        ) : database_safety.index(
            "function Invoke-TicketboxWithPgPassFile"
        )
    ]
    assert "New-TicketboxProtectedFileStream -Path $passfile" in passfile_writer
    assert "Write-TicketboxProtectedUtf8FileDurable" not in passfile_writer

    protected_action = database_safety[
        database_safety.index(
            "function Invoke-TicketboxWithPgPassFile"
        ) : database_safety.index(
            "function Invoke-TicketboxPgDumpCustom"
        )
    ]
    assert "return & $Action" not in protected_action
    assert "$actionResults = @(& $Action $protected.DatabaseUrl)" in protected_action
    assert "return $actionResult" in protected_action
    if sys.platform == "win32":
        from app.services.secure_file import (
            hold_protected_file_for_read,
            write_protected_file_exclusive,
        )

        protected_file = (tmp_path / "python-protected-passfile").resolve()
        write_protected_file_exclusive(protected_file, "secret\n")
        with hold_protected_file_for_read(protected_file) as held:
            assert held == protected_file
        protected_file.unlink()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows atomic configuration contract")
def test_postgres_managed_block_replacement_preserves_following_configuration(tmp_path: Path) -> None:
    configurations = {
        "bounded": (
            "# BEGIN Ticketbox installer overrides\r\n"
            "listen_addresses = '127.0.0.1'\r\n"
            "port = 5432\r\n"
            "# END Ticketbox installer overrides\r\n"
        ),
        "legacy": (
            "# Ticketbox installer overrides\r\n"
            "listen_addresses = '127.0.0.1'\r\n"
            "port = 5432\r\n"
        ),
    }
    for engine_index, engine in enumerate(_powershell_engines()):
        for format_name, managed_block in configurations.items():
            pg_data = tmp_path / f"pg-managed-{engine_index}-{format_name}"
            pg_data.mkdir()
            config_path = pg_data / "postgresql.conf"
            config_path.write_text(
                "shared_buffers = '128MB'\r\n"
                "\r\n"
                f"{managed_block}"
                "\r\n"
                "custom_after_ticketbox = 'must-survive'\r\n",
                encoding="ascii",
                newline="",
            )
            harness = tmp_path / f"pg-managed-{engine_index}-{format_name}.ps1"
            _write_ps1(
                harness,
                f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(DATABASE_SCRIPT)}'
$PgData = '{_ps_literal(pg_data)}'
$PgPort = 6543
Set-TicketboxPostgresInstallerConfiguration
$content = [System.IO.File]::ReadAllText('{_ps_literal(config_path)}', [System.Text.Encoding]::ASCII)
$begin = $content.IndexOf('# BEGIN Ticketbox installer overrides')
$end = $content.IndexOf('# END Ticketbox installer overrides')
$suffix = $content.IndexOf("custom_after_ticketbox = 'must-survive'")
if ($suffix -lt 0 -or $begin -le $suffix -or $end -le $begin) {{ throw 'managed block was not authoritative at EOF' }}
if ($content -notmatch '(?m)^port = 6543\r?$') {{ throw 'managed port was not replaced' }}
if ($content -match '(?m)^port = 5432\r?$') {{ throw 'stale managed port survived' }}
$autoConfig = Join-Path $PgData 'postgresql.auto.conf'
[System.IO.File]::WriteAllText(
    $autoConfig,
    "listen_addresses = '*'$([Environment]::NewLine)",
    [System.Text.Encoding]::ASCII
)
$autoOverrideRejected = $false
try {{ Set-TicketboxPostgresInstallerConfiguration }} catch {{ $autoOverrideRejected = $true }}
if (-not $autoOverrideRejected) {{ throw 'postgresql.auto.conf loopback override was accepted' }}
""",
            )
            result = _run_ps1(engine, harness)
            assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell secret-length contract")
def test_http_bootstrap_secret_uses_dynamic_32_and_64_byte_config(tmp_path: Path) -> None:
    harness = tmp_path / "http-bootstrap-secret-length.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(DATABASE_SCRIPT).replace("'", "''")}'
foreach ($case in @(
    [pscustomobject]@{{ Bytes = 32; Encoded = 43 }},
    [pscustomobject]@{{ Bytes = 64; Encoded = 86 }}
)) {{
    $SecretByteCount = [int]$case.Bytes
    $value = New-HttpBootstrapSecret
    if ($value.Length -ne [int]$case.Encoded -or $value -cnotmatch '^[A-Za-z0-9_-]+$') {{
        throw "unexpected base64url length for $($case.Bytes) bytes"
    }}
    Assert-HttpBootstrapSecretValue $value
    $paddingLength = (4 - ($value.Length % 4)) % 4
    $decoded = [Convert]::FromBase64String(
        $value.Replace('-', '+').Replace('_', '/') + ('=' * $paddingLength)
    )
    if ($decoded.Length -ne [int]$case.Bytes) {{
        throw "decoded secret length mismatch for $($case.Bytes) bytes"
    }}
}}
$SecretByteCount = 31
$rejected = $false
try {{ New-HttpBootstrapSecret | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'sub-256-bit HTTP bootstrap secret was accepted' }}
""",
        encoding="utf-8-sig",
    )
    for engine in _powershell_engines():
        result = _run_ps1(engine, harness)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL and PowerShell contract")
def test_fresh_init_crash_recovery_and_verified_cleanup(tmp_path: Path) -> None:
    native_stub = _build_native_stub(tmp_path)
    pg_bin = tmp_path / "pg-bin"
    pg_bin.mkdir()
    shutil.copy2(native_stub, pg_bin / "initdb.exe")

    for index, engine in enumerate(_powershell_engines()):
        root = tmp_path / f"state-{index}"
        app_data = root / "app"
        app_data.mkdir(parents=True)
        trace_path = root / "native-argv.txt"
        harness = root / "database-recovery-behavior.ps1"
        script = r"""
$ErrorActionPreference = 'Stop'
. '__INSTALLATION_SAFETY__'
. '__DATABASE_SAFETY__'
. '__DATABASE_SCRIPT__'

$DataRoot = '__DATA_ROOT__'
$PgData = Join-Path $DataRoot 'pgdata'
$AppData = Join-Path $DataRoot 'app'
$EnvPath = Join-Path $AppData '.env'
$PgBin = '__PG_BIN__'
$PgPort = 5544
$DbName = 'ticketbox'
$DbRole = 'ticketbox'
$SecretByteCount = 32
$StopTimeoutMs = 25000
$DatabaseToolTimeoutMs = 10000
$BackendPort = 8000
$Timezone = 'Asia/Shanghai'
$PublicBaseUrl = ''
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:PostgresBootstrapAclAccounts = @($currentAccount)
$script:PostgresBootstrapAclOwnerAccount = $currentAccount
$env:TICKETBOX_TEST_ARGV_TRACE = '__TRACE_PATH__'

function Write-Step { param([string]$Message) }
function Write-Ok { param([string]$Message) }
function ConvertTo-TicketboxTimeoutSeconds([int]$Milliseconds) {
    return [int][Math]::Ceiling($Milliseconds / 1000.0)
}

$env:TICKETBOX_TEST_NATIVE_MODE = 'partial-init-fail'
$partialFailed = $false
try { Initialize-PgClusterIfNeeded | Out-Null } catch { $partialFailed = $true }
if (-not $partialFailed) { throw 'partial initdb failure was accepted' }
$recoveryPath = Get-PostgresBootstrapRecoveryPath
if (-not (Test-Path -LiteralPath $recoveryPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $PgData 'partial-init.tmp') -PathType Leaf) -or
    (Test-Path -LiteralPath (Join-Path $PgData 'PG_VERSION'))) {
    throw 'partial initdb evidence was not preserved for a safe retry'
}
$env:TICKETBOX_TEST_NATIVE_MODE = ''
$firstResult = Initialize-PgClusterIfNeeded
if ($null -ne $firstResult) { throw 'fresh init returned a secret' }
if (Test-Path -LiteralPath (Join-Path $PgData 'partial-init.tmp')) {
    throw 'recoverable partial initdb directory was not cleaned before retry'
}
if (-not (Test-Path -LiteralPath $recoveryPath -PathType Leaf)) {
    throw 'fresh init did not persist recovery state'
}
$state = Read-PostgresBootstrapRecoveryState
if ($state.HttpBootstrapSecret.Length -ne 43 -or
    $state.HttpBootstrapSecret -cnotmatch '^[A-Za-z0-9_-]{43}$') {
    throw 'HTTP bootstrap secret is not unpadded base64url'
}
$decodedHttpSecret = [Convert]::FromBase64String(
    $state.HttpBootstrapSecret.Replace('-', '+').Replace('_', '/') + '='
)
if ($decodedHttpSecret.Length -ne 32) {
    throw 'HTTP bootstrap secret does not preserve 256 bits'
}
$secondHttpSecret = New-HttpBootstrapSecret
if ($secondHttpSecret -ceq $state.HttpBootstrapSecret) {
    throw 'HTTP bootstrap secret generator repeated output'
}
$firstTrace = Get-Content -LiteralPath '__TRACE_PATH__' -Raw -Encoding UTF8
foreach ($secret in @($state.SuperuserPassword, $state.RolePassword, $state.HttpBootstrapSecret)) {
    if ($firstTrace.Contains($secret)) { throw 'secret appeared in initdb argv' }
}
if (-not $firstTrace.Contains("--pwfile=$recoveryPath")) {
    throw 'initdb did not receive the protected recovery path'
}

[void](Initialize-PgClusterIfNeeded)
$secondTrace = Get-Content -LiteralPath '__TRACE_PATH__' -Raw -Encoding UTF8
if ($secondTrace -cne $firstTrace) { throw 'recovery reran initdb' }
$recoveredState = Read-PostgresBootstrapRecoveryState
if ($recoveredState.SuperuserPassword -cne $state.SuperuserPassword -or
    $recoveredState.RolePassword -cne $state.RolePassword -or
    $recoveredState.HttpBootstrapSecret -cne $state.HttpBootstrapSecret) {
    throw 'crash recovery changed persisted secrets'
}

$script:roleExists = $false
$script:databaseExists = $false
$script:failAfterRole = $true
$script:alterObserved = $false
function Invoke-Psql([string]$Database, [string]$Sql, [string]$Password) {
    if ($Password -cne $state.SuperuserPassword) { throw 'wrong superuser password' }
    if ($Sql.StartsWith('SELECT 1 FROM pg_roles', [StringComparison]::Ordinal)) {
        if ($script:roleExists) { return '1' }
        return ''
    }
    if ($Sql.StartsWith('CREATE ROLE', [StringComparison]::Ordinal)) {
        if (-not $Sql.Contains($state.RolePassword)) { throw 'role password changed' }
        $script:roleExists = $true
        return ''
    }
    if ($Sql.StartsWith('ALTER ROLE', [StringComparison]::Ordinal)) {
        if (-not $Sql.Contains($state.RolePassword)) { throw 'role password changed' }
        $script:alterObserved = $true
        return ''
    }
    if ($Sql.StartsWith('SELECT pg_get_userbyid', [StringComparison]::Ordinal)) {
        if ($script:failAfterRole) {
            $script:failAfterRole = $false
            throw 'simulated crash after role creation'
        }
        if ($script:databaseExists) { return $DbRole }
        return ''
    }
    if ($Sql.StartsWith('CREATE DATABASE', [StringComparison]::Ordinal)) {
        $script:databaseExists = $true
        return ''
    }
    throw 'unexpected SQL shape'
}
function Assert-TicketboxConnectedPostgresDataRoot {
    param(
        [string]$PsqlPath,
        [string]$DatabaseUrl,
        [string]$ExpectedDataRoot,
        [int]$ExpectedPort,
        [string]$Password,
        [int]$TimeoutMilliseconds
    )
    if ($Password -cne $state.RolePassword) { throw 'application role password mismatch' }
    if ($ExpectedDataRoot -cne $PgData) { throw 'data root mismatch' }
    if ($ExpectedPort -ne $PgPort) { throw 'port mismatch' }
    if ($TimeoutMilliseconds -le 0) { throw 'database tool timeout missing' }
}

$crashed = $false
try { Prepare-DatabaseIfNeeded $null | Out-Null }
catch {
    $crashed = $true
    foreach ($secret in @($state.SuperuserPassword, $state.RolePassword, $state.HttpBootstrapSecret)) {
        if ($_.Exception.Message.Contains($secret)) { throw 'secret leaked through crash error' }
    }
}
if (-not $crashed -or -not $script:roleExists -or $script:databaseExists) {
    throw 'role-only crash was not simulated'
}
if (-not (Test-Path -LiteralPath $recoveryPath) -or (Test-Path -LiteralPath $EnvPath)) {
    throw 'role-only crash lost recovery state or wrote env too early'
}

$script:originalSensitiveRemove = ${function:Remove-TicketboxSensitiveFile}
$script:blockRecoveryCleanup = $true
function Remove-TicketboxSensitiveFile([string]$Path) {
    if ($script:blockRecoveryCleanup -and $Path -ceq $recoveryPath) {
        throw 'simulated recovery cleanup failure'
    }
    & $script:originalSensitiveRemove $Path
}
$cleanupFailed = $false
try { Prepare-DatabaseIfNeeded $null | Out-Null }
catch { $cleanupFailed = $true }
if (-not $cleanupFailed -or
    -not (Test-Path -LiteralPath $recoveryPath) -or
    -not (Test-Path -LiteralPath $EnvPath)) {
    throw 'recovery cleanup failure did not fail closed after env persistence'
}
if (-not $script:alterObserved -or -not $script:databaseExists) {
    throw 'retry did not reuse the role password and finish the database'
}

$script:blockRecoveryCleanup = $false
Set-Item -Path Function:Remove-TicketboxSensitiveFile -Value $script:originalSensitiveRemove
[void](Prepare-DatabaseIfNeeded $null)
if (Test-Path -LiteralPath $recoveryPath) {
    throw 'verified success did not remove recovery state'
}
$envBytes = [System.IO.File]::ReadAllBytes($EnvPath)
if ($envBytes.Length -ge 3 -and
    $envBytes[0] -eq 0xEF -and $envBytes[1] -eq 0xBB -and $envBytes[2] -eq 0xBF) {
    throw '.env contains a UTF-8 BOM'
}
"""
        replacements = {
            "__INSTALLATION_SAFETY__": _ps_literal(INSTALLATION_SAFETY_SCRIPT),
            "__DATABASE_SAFETY__": _ps_literal(DATABASE_SAFETY_SCRIPT),
            "__DATABASE_SCRIPT__": _ps_literal(DATABASE_SCRIPT),
            "__DATA_ROOT__": _ps_literal(root),
            "__PG_BIN__": _ps_literal(pg_bin),
            "__TRACE_PATH__": _ps_literal(trace_path),
        }
        for placeholder, value in replacements.items():
            script = script.replace(placeholder, value)
        _write_ps1(harness, script)
        result = _run_ps1(engine, harness)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL and PowerShell contract")
def test_malformed_and_insecure_recovery_files_fail_closed(tmp_path: Path) -> None:
    for index, engine in enumerate(_powershell_engines()):
        root = tmp_path / f"security-{index}"
        root.mkdir()
        harness = root / "database-recovery-security.ps1"
        script = r"""
$ErrorActionPreference = 'Stop'
. '__INSTALLATION_SAFETY__'
. '__DATABASE_SCRIPT__'
$DataRoot = '__DATA_ROOT__'
$AppData = Join-Path $DataRoot 'app'
New-Item -ItemType Directory -Path $AppData -Force | Out-Null
$SecretByteCount = 32
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:PostgresBootstrapAclAccounts = @($currentAccount)
$script:PostgresBootstrapAclOwnerAccount = $currentAccount

$fixedHttpSecret = [Convert]::ToBase64String((New-Object 'System.Byte[]' 32)).TrimEnd(
    [char[]]@([char]'=')
).Replace('+', '-').Replace('/', '_')
Assert-HttpBootstrapSecretValue $fixedHttpSecret
$paddedSecretRejected = $false
try { Assert-HttpBootstrapSecretValue ($fixedHttpSecret + '=') }
catch {
    $paddedSecretRejected = $true
    if ($_.Exception.Message.Contains($fixedHttpSecret)) {
        throw 'fixed HTTP bootstrap secret leaked through validation error'
    }
}
if (-not $paddedSecretRejected) { throw 'padded HTTP bootstrap secret was accepted' }

$state = Get-OrCreatePostgresBootstrapRecoveryState
$recoveryPath = Get-PostgresBootstrapRecoveryPath
[System.IO.File]::WriteAllText(
    $recoveryPath,
    'malformed-secret-sentinel',
    [System.Text.Encoding]::ASCII
)
$malformedRejected = $false
try { Read-PostgresBootstrapRecoveryState | Out-Null }
catch {
    $malformedRejected = $true
    if ($_.Exception.Message.Contains('malformed-secret-sentinel')) {
        throw 'malformed content leaked through error text'
    }
}
if (-not $malformedRejected) { throw 'malformed recovery state was accepted' }

$validPayload = ConvertTo-PostgresBootstrapRecoveryPayload $state
[System.IO.File]::WriteAllText($recoveryPath, $validPayload, [System.Text.Encoding]::ASCII)
& icacls.exe $recoveryPath /grant '*S-1-1-0:R' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'failed to seed insecure recovery ACL' }
$unsafeRejected = $false
try { Read-PostgresBootstrapRecoveryState | Out-Null }
catch { $unsafeRejected = $true }
if (-not $unsafeRejected) { throw 'recovery state with an extra ACL was accepted' }

Set-TicketboxExactFileAcl `
    -Path $recoveryPath `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$roundTrip = Read-PostgresBootstrapRecoveryState
if ($roundTrip.SuperuserPassword -cne $state.SuperuserPassword) {
    throw 'secure recovery state stopped working after ACL repair'
}
Remove-TicketboxSensitiveFile $recoveryPath
New-Item -ItemType Directory -Path $recoveryPath | Out-Null
$nonFileRejected = $false
try { Read-PostgresBootstrapRecoveryState | Out-Null }
catch { $nonFileRejected = $true }
if (-not $nonFileRejected) { throw 'recovery directory was accepted as a file' }
Remove-Item -LiteralPath $recoveryPath -Force
"""
        replacements = {
            "__INSTALLATION_SAFETY__": _ps_literal(INSTALLATION_SAFETY_SCRIPT),
            "__DATABASE_SCRIPT__": _ps_literal(DATABASE_SCRIPT),
            "__DATA_ROOT__": _ps_literal(root),
        }
        for placeholder, value in replacements.items():
            script = script.replace(placeholder, value)
        _write_ps1(harness, script)
        result = _run_ps1(engine, harness)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native stderr contract")
def test_invoke_psql_sanitizes_ps51_native_stderr(tmp_path: Path) -> None:
    native_stub = _build_native_stub(tmp_path)
    pg_bin = tmp_path / "psql-bin"
    pg_bin.mkdir()
    shutil.copy2(native_stub, pg_bin / "psql.exe")

    for index, engine in enumerate(_powershell_engines()):
        trace_path = tmp_path / f"psql-argv-{index}.txt"
        harness = tmp_path / f"psql-native-stderr-{index}.ps1"
        script = r"""
$ErrorActionPreference = 'Stop'
. '__INSTALLATION_SAFETY__'
. '__DATABASE_SAFETY__'
. '__DATABASE_SCRIPT__'
$PgBin = '__PG_BIN__'
$PgPort = 5544
$DatabaseToolTimeoutMs = 10000
$env:TICKETBOX_TEST_ARGV_TRACE = '__TRACE_PATH__'
$env:TICKETBOX_TEST_NATIVE_MODE = 'stderr'
$env:PGPASSWORD = 'parent-password-sentinel'
$env:PGPASSFILE = 'parent-passfile-sentinel'
$env:PGHOSTADDR = '203.0.113.7'
$env:PGPORT = '6543'
$env:PGSERVICE = 'parent-service-sentinel'
$passDirectory = Get-TicketboxProtectedPgPassDirectory
$stalePaths = @(
    (Join-Path $passDirectory.Path ('.ticketbox-pgpass-stale-empty-' + $PID)),
    (Join-Path $passDirectory.Path ('.ticketbox-protected-stale-truncated-' + $PID + '.tmp'))
)
$staleSecurity = New-TicketboxProtectedFileSecurity `
    -FullControlAccounts $passDirectory.FullControlAccounts `
    -OwnerAccount $passDirectory.OwnerAccount
$emptyStream = New-TicketboxProtectedFileStream -Path $stalePaths[0] -Security $staleSecurity
$emptyStream.Dispose()
$truncatedStream = New-TicketboxProtectedFileStream -Path $stalePaths[1] -Security $staleSecurity
try {
    $truncatedStream.Write([byte[]]@(0xC3), 0, 1)
    $truncatedStream.Flush($true)
}
finally { $truncatedStream.Dispose() }
foreach ($stalePath in $stalePaths) {
    [System.IO.File]::SetLastWriteTimeUtc($stalePath, [DateTime]::UtcNow.AddHours(-3))
}
Get-TicketboxProtectedPgPassDirectory | Out-Null
foreach ($stalePath in $stalePaths) {
    if (Test-Path -LiteralPath $stalePath) { throw 'stale crash residue was not removed' }
}
$legacyStage = Join-Path $passDirectory.Path ('.ticketbox-protected-test-' + $PID + '.tmp')
Write-TicketboxProtectedUtf8FileDurable `
    -Path $legacyStage `
    -Text 'interrupted legacy staging' `
    -FullControlAccounts $passDirectory.FullControlAccounts `
    -OwnerAccount $passDirectory.OwnerAccount
$caught = $false
try {
    Invoke-Psql 'postgres' 'SELECT sql-secret-sentinel' 'pg-password-sentinel' | Out-Null
}
catch {
    $caught = $true
    $message = $_.Exception.Message
    foreach ($secret in @(
        'native-stderr-secret-sentinel',
        'sql-secret-sentinel',
        'pg-password-sentinel'
    )) {
        if ($message.Contains($secret)) { throw 'Invoke-Psql leaked native details' }
    }
    if (-not $message.Contains('db=postgres') -or -not $message.Contains('exit=9')) {
        throw 'Invoke-Psql did not throw its sanitized error'
    }
}
if (-not $caught) { throw 'native psql failure was not caught' }
if ($ErrorActionPreference -ne 'Stop') { throw 'ErrorActionPreference was not restored' }
if ($env:PGPASSWORD -cne 'parent-password-sentinel') { throw 'PGPASSWORD was not restored' }
if ($env:PGPASSFILE -cne 'parent-passfile-sentinel') { throw 'PGPASSFILE was not restored' }
if ($env:PGHOSTADDR -cne '203.0.113.7') { throw 'PGHOSTADDR was not restored' }
if ($env:PGPORT -cne '6543') { throw 'PGPORT was not restored' }
if ($env:PGSERVICE -cne 'parent-service-sentinel') { throw 'PGSERVICE was not restored' }
$trace = Get-Content -LiteralPath '__TRACE_PATH__' -Raw -Encoding UTF8
foreach ($secret in @('sql-secret-sentinel', 'pg-password-sentinel', 'parent-password-sentinel')) {
    if ($trace.Contains($secret)) { throw 'secret appeared in psql argv' }
}

$env:TICKETBOX_TEST_NATIVE_MODE = 'success'
$output = Invoke-Psql 'postgres' 'SELECT 1' 'pg-password-sentinel'
if ($output -cne '1') { throw 'successful psql stdout was not returned' }
if ($ErrorActionPreference -ne 'Stop') { throw 'success changed ErrorActionPreference' }
if ($env:PGPASSWORD -cne 'parent-password-sentinel') { throw 'success changed PGPASSWORD' }
if ($env:PGPASSFILE -cne 'parent-passfile-sentinel') { throw 'success changed PGPASSFILE' }
if ($env:PGHOSTADDR -cne '203.0.113.7') { throw 'success changed PGHOSTADDR' }
if ($env:PGPORT -cne '6543') { throw 'success changed PGPORT' }
if ($env:PGSERVICE -cne 'parent-service-sentinel') { throw 'success changed PGSERVICE' }
Remove-TicketboxProtectedPgPassArtifact `
    -Path $legacyStage `
    -FullControlAccounts $passDirectory.FullControlAccounts `
    -OwnerAccount $passDirectory.OwnerAccount
"""
        replacements = {
            "__INSTALLATION_SAFETY__": _ps_literal(INSTALLATION_SAFETY_SCRIPT),
            "__DATABASE_SAFETY__": _ps_literal(DATABASE_SAFETY_SCRIPT),
            "__DATABASE_SCRIPT__": _ps_literal(DATABASE_SCRIPT),
            "__PG_BIN__": _ps_literal(pg_bin),
            "__TRACE_PATH__": _ps_literal(trace_path),
        }
        for placeholder, value in replacements.items():
            script = script.replace(placeholder, value)
        _write_ps1(harness, script)
        result = _run_ps1(engine, harness)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, f"{engine}:\n{combined}"
        assert "native-stderr-secret-sentinel" not in combined
        assert "sql-secret-sentinel" not in combined
        assert "pg-password-sentinel" not in combined
