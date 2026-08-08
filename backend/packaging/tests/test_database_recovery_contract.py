import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
DATABASE_SCRIPT = PACKAGING / "windows_bundled_database.ps1"
INSTALL_SCRIPT = PACKAGING / "install_bundled_services.ps1"
DATABASE_SAFETY_SCRIPT = PACKAGING / "windows_database_safety.ps1"
INSTALLATION_SAFETY_SCRIPT = PACKAGING / "windows_installation_safety.ps1"
SERVICE_LIFECYCLE_SCRIPT = PACKAGING / "windows_service_lifecycle.ps1"
PREPARE_SCRIPT = PACKAGING / "prepare_bundled_upgrade.ps1"


def _read_database_script() -> str:
    return DATABASE_SCRIPT.read_text(encoding="utf-8-sig")


def _powershell_engines() -> list[str]:
    return list(powershell_contract_engines())


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
            if (Directory.Exists(dataRoot))
            {
                return 24;
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL host contract")
def test_postgres_host_authority_accepts_only_managed_physical_or_runtime_paths(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(_powershell_engines()):
        root = tmp_path / f"postgres-host-authority-{index}"
        install_dir = root / "program"
        data_root = root / "managed"
        physical_pgdata = data_root / "pgdata"
        runtime_data_root = root / "runtime-binding" / "data-root"
        runtime_pgdata = runtime_data_root / "pgdata"
        pg_bin = install_dir / "pg" / "bin"
        for directory in (physical_pgdata, runtime_pgdata, pg_bin):
            directory.mkdir(parents=True)
        pg_ctl = pg_bin / "pg_ctl.exe"
        psql = pg_bin / "psql.exe"
        pg_ctl.write_bytes(b"stub")
        psql.write_bytes(b"stub")
        script = tmp_path / f"postgres-host-authority-{index}.ps1"
        _write_ps1(
            script,
            rf"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(DATABASE_SAFETY_SCRIPT)}'

$installDir = '{_ps_literal(install_dir)}'
$dataRoot = '{_ps_literal(data_root)}'
$physicalPgData = '{_ps_literal(physical_pgdata)}'
$runtimeDataRoot = '{_ps_literal(runtime_data_root)}'
$runtimePgData = '{_ps_literal(runtime_pgdata)}'
$pgCtl = '{_ps_literal(pg_ctl)}'
$psql = '{_ps_literal(psql)}'
$script:activePgData = $physicalPgData
$script:bindingMode = 'exact'
$script:bindingReads = 0
$script:reparseChecks = New-Object 'Collections.Generic.List[string]'

function ConvertTo-TicketboxWin32CanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        (ConvertTo-TicketboxWin32CanonicalPath $Left),
        (ConvertTo-TicketboxWin32CanonicalPath $Right),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Test-TicketboxPathWithin([string]$Path, [string]$Parent) {{
    $candidate = ConvertTo-TicketboxWin32CanonicalPath $Path
    $container = ConvertTo-TicketboxWin32CanonicalPath $Parent
    return (
        (Test-TicketboxPathEquals $candidate $container) -or
        $candidate.StartsWith($container + '\', [StringComparison]::OrdinalIgnoreCase)
    )
}}
function Test-TicketboxServiceExists([string]$Name) {{
    return $Name -ceq 'TicketboxPg'
}}
function Assert-TicketboxServiceAccount {{
    param([string]$Name, [string]$ExpectedAccount)
    if ($Name -cne 'TicketboxPg' -or $ExpectedAccount -cne 'NT SERVICE\TicketboxPg') {{
        throw 'service account contract drifted'
    }}
}}
function Get-TicketboxServiceImagePath([string]$Name) {{ return 'scm-owned' }}
function Split-TicketboxWindowsCommandLine([string]$CommandLine) {{
    return @(
        $pgCtl, 'runservice', '-N', 'TicketboxPg',
        '-D', $script:activePgData, '-w'
    )
}}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{
    $script:reparseChecks.Add((ConvertTo-TicketboxWin32CanonicalPath $Path))
}}
function Assert-TicketboxPgServiceCommand {{
    param($Name, $ExpectedExecutable, $ExpectedServiceName, $ExpectedDataRoot)
    if (
        $Name -cne 'TicketboxPg' -or
        $ExpectedServiceName -cne 'TicketboxPg' -or
        -not (Test-TicketboxPathEquals $ExpectedExecutable $pgCtl) -or
        -not (Test-TicketboxPathEquals $ExpectedDataRoot $script:activePgData)
    ) {{
        throw 'exact PostgreSQL SCM command was not revalidated'
    }}
}}
function Get-TicketboxRuntimeDataRootPath {{ return $runtimeDataRoot }}
function Get-TicketboxServiceSid([string]$Name) {{
    if ($Name -ceq 'TicketboxPg') {{ return 'S-1-5-80-1-2-3-4-5' }}
    if ($Name -ceq 'TicketboxBackend') {{ return 'S-1-5-80-6-7-8-9-10' }}
    throw "unexpected service SID request: $Name"
}}
function Read-TicketboxRuntimeDataBinding {{
    param(
        $DataRoot,
        $InstallDir,
        [string[]]$ServiceReadExecuteAccounts,
        $DataRootMarkerAclPhase,
        $ExpectedBackendServiceName
    )
    $script:bindingReads += 1
    if (
        -not (Test-TicketboxPathEquals $DataRoot $dataRoot) -or
        -not (Test-TicketboxPathEquals $InstallDir $installDir) -or
        ($ServiceReadExecuteAccounts -join '|') -cne
            'S-1-5-80-1-2-3-4-5|S-1-5-80-6-7-8-9-10' -or
        $DataRootMarkerAclPhase -cne 'backend_read_optional' -or
        $ExpectedBackendServiceName -cne 'TicketboxBackend'
    ) {{
        throw 'runtime binding was not read through the exact installation contract'
    }}
    if ($script:bindingMode -ceq 'reject') {{
        throw 'runtime junction marker mismatch'
    }}
    $boundPgData = if ($script:bindingMode -ceq 'mismatch') {{
        Join-Path $runtimeDataRoot 'foreign-pgdata'
    }} else {{ $runtimePgData }}
    $volumeIdentity = if (
        $script:bindingMode -ceq 'drift' -and $script:bindingReads -eq 2
    ) {{ 'volume-B' }} else {{ 'volume-A' }}
    return [pscustomobject]@{{
        RuntimePgData = $boundPgData
        DataVolumeIdentity = $volumeIdentity
        VolumeBoundTarget = 'volume-target-A'
    }}
}}
function Get-TicketboxServiceProcessId([string]$Name) {{ return 9876 }}

function Write-TestPostmasterPid([string]$PgData) {{
    [IO.File]::WriteAllText(
        (Join-Path $PgData 'postmaster.pid'),
        "4321`r`n$PgData`r`n0`r`n5544`r`n",
        [Text.Encoding]::ASCII
    )
}}
function Resolve-TestAuthority {{
    return Resolve-TicketboxPostgresServiceHostAuthority `
        -ServiceName 'TicketboxPg' `
        -ExpectedPgCtlPath $pgCtl `
        -DataRoot $dataRoot `
        -InstallDir $installDir `
        -BackendServiceName 'TicketboxBackend'
}}
function Assert-RejectedBinding([string]$Mode, [string]$MessageFragment) {{
    $script:bindingMode = $Mode
    $script:bindingReads = 0
    $accepted = $true
    try {{ [void](Resolve-TestAuthority) }}
    catch {{
        $accepted = $false
        if (
            $_.Exception.Data['TicketboxInstallPublicFailureCode'] -cne
                'postgres_host_authority_validation_failed' -or
            $_.Exception.Message -notlike "*$MessageFragment*"
        ) {{ throw }}
    }}
    if ($accepted) {{ throw "untrusted runtime binding was accepted: $Mode" }}
}}

Write-TestPostmasterPid $physicalPgData
$physical = Resolve-TestAuthority
if (
    $physical.Schema -cne 'ticketbox-windows-postgres-host-authority-v1' -or
    $physical.UsesRuntimeBinding -or
    $physical.DataVolumeIdentity -cne '' -or
    $physical.ServiceProcessId -ne 9876 -or
    $physical.PostmasterProcessId -ne 4321 -or
    $physical.Port -ne 5544 -or
    -not (Test-TicketboxPathEquals $physical.PgData $physicalPgData) -or
    $script:bindingReads -ne 0 -or
    $script:reparseChecks.Count -ne 3 -or
    -not ($script:reparseChecks | Where-Object {{
        Test-TicketboxPathEquals $_ $physicalPgData
    }})
) {{
    throw 'direct physical PGDATA authority drifted'
}}

$script:activePgData = $runtimePgData
$script:bindingMode = 'exact'
$script:bindingReads = 0
$script:reparseChecks.Clear()
Write-TestPostmasterPid $runtimePgData
$runtime = Resolve-TestAuthority
if (
    -not $runtime.UsesRuntimeBinding -or
    $runtime.DataVolumeIdentity -cne 'volume-A' -or
    $script:bindingReads -ne 2 -or
    $script:reparseChecks.Count -ne 2 -or
    ($script:reparseChecks | Where-Object {{
        (Test-TicketboxPathEquals $_ $runtimeDataRoot) -or
        (Test-TicketboxPathEquals $_ $runtimePgData)
    }})
) {{
    throw 'verified runtime PGDATA authority drifted or used legacy reparse rejection'
}}

Assert-RejectedBinding 'mismatch' 'runtime binding'
Assert-RejectedBinding 'reject' 'runtime junction marker mismatch'
Assert-RejectedBinding 'drift' '发生漂移'
""",
        )
        result = _run_ps1(engine, script)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_bootstrap_recovery_static_contract(tmp_path: Path) -> None:
    database = _read_database_script()
    database_safety = DATABASE_SAFETY_SCRIPT.read_text(encoding="utf-8-sig")
    install = INSTALL_SCRIPT.read_text(encoding="utf-8-sig")

    assert '$script:PostgresBootstrapRecoveryFileName = ".postgres-bootstrap-password"' in database
    assert '$script:PostgresBootstrapAclAccounts = @("SYSTEM", "BUILTIN\\Administrators")' in database
    assert '$script:PostgresBootstrapAclOwnerAccount = "SYSTEM"' in database
    assert 'FileMode]::CreateNew' in database
    assert 'FileOptions]::WriteThrough' in database
    assert '$stream.Flush($true)' in database
    assert 'Move-TicketboxFileAtomically -Source $tempPath -Destination $pwfile' in database
    assert 'Set-TicketboxExactFileAcl `' in database
    assert 'Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile' in database
    assert 'Get-OrCreatePostgresBootstrapRecoveryState' in database
    assert "function Repair-PostgresBootstrapRecoveryFileAcl" in database
    assert "function Protect-PostgresBootstrapRecoveryFileAfterAclNormalization" in database
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
    fresh_write = database.index(
        "$bootstrapState = Get-OrCreatePostgresBootstrapRecoveryState"
    )
    initdb_dispatch = database.index(
        "$initResult = if ($null -ne $InitdbInvoker)", fresh_write
    )
    direct_initdb_fallback = database.index(
        'Join-Path $PgBin "initdb.exe"', initdb_dispatch
    )
    assert fresh_write < initdb_dispatch < direct_initdb_fallback

    set_acl = install[
        install.index("function Set-TicketboxAcl(") : install.index(
            "function Initialize-TicketboxInstallerStateArtifacts"
        )
    ]
    assert '[string[]]$PrivilegedAccounts = @("SYSTEM", "BUILTIN\\Administrators")' in set_acl
    assert '[string]$OwnerAccount = "SYSTEM"' in set_acl
    app_acl = set_acl.index("-Path $AppData")
    bootstrap_reprotection = set_acl.index(
        "Protect-PostgresBootstrapRecoveryFileAfterAclNormalization",
        app_acl,
    )
    installer_state = set_acl.index(
        "Initialize-TicketboxInstallerStateDirectory",
        bootstrap_reprotection,
    )
    assert app_acl < bootstrap_reprotection < installer_state

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
def test_service_owned_initdb_uses_a_separate_single_secret_authority() -> None:
    database = _read_database_script()
    install = INSTALL_SCRIPT.read_text(encoding="utf-8-sig")
    safety = INSTALLATION_SAFETY_SCRIPT.read_text(encoding="utf-8-sig")
    service_contract = (PACKAGING / "windows_service_contract.ps1").read_text(
        encoding="utf-8-sig"
    )
    prepare = PREPARE_SCRIPT.read_text(encoding="utf-8-sig")
    uninstall = (PACKAGING / "uninstall_bundled_services.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert (
        '$script:PostgresBootstrapAclAccounts = @("SYSTEM", "BUILTIN\\Administrators")'
        in database
    )
    bootstrap_writer = database[
        database.index("function Write-PostgresBootstrapRecoveryState") : database.index(
            "function Read-PostgresBootstrapRecoveryState"
        )
    ]
    assert "NT SERVICE\\$PgServiceName" not in bootstrap_writer
    assert '".ticketbox-initdb-password"' in service_contract
    assert '"--no-restart"' in service_contract
    assert '"--no-log"' in service_contract
    assert '"--kill-process-tree"' in service_contract
    assert "function Assert-TicketboxInitdbPasswordFileAcl" in safety
    assert "[Security.AccessControl.FileSystemRights]::Read" in safety
    assert "[Security.AccessControl.InheritanceFlags]::None" in safety
    assert "[Security.AccessControl.PropagationFlags]::None" in safety
    assert "function Write-TicketboxInitdbPasswordFileAtomically" in safety
    security_factory = safety[
        safety.index("function New-TicketboxInitdbPasswordFileSecurity") : safety.index(
            "function Write-TicketboxInitdbPasswordFileAtomically"
        )
    ]
    assert "SetAccessRuleProtection($true, $false)" in security_factory
    assert "[Security.AccessControl.FileSystemRights]::FullControl" in security_factory
    assert "[Security.AccessControl.FileSystemRights]::Read" in security_factory
    atomic_writer = safety[
        safety.index("function Write-TicketboxInitdbPasswordFileAtomically") : safety.index(
            "function Assert-TicketboxInitdbPasswordFileAcl"
        )
    ]
    security_created = atomic_writer.index("New-TicketboxInitdbPasswordFileSecurity")
    stream_created = atomic_writer.index("New-TicketboxProtectedFileStream")
    secret_written = atomic_writer.index("$stream.Write(")
    assert security_created < stream_created < secret_written
    assert "$stream.Flush($true)" in atomic_writer
    assert "Write-TicketboxProtectedUtf8Artifact" not in atomic_writer
    assert "Invoke-TicketboxIcaclsChecked" not in atomic_writer
    assert "WriteAllText" not in atomic_writer
    assert ".tmp" not in atomic_writer
    transient_writer = install[
        install.index("function Write-TicketboxInitdbPasswordFile") : install.index(
            "function Remove-TicketboxInitdbPasswordFileIfPresent"
        )
    ]
    assert "-Text $SuperuserPassword" in transient_writer
    assert "RolePassword" not in transient_writer
    assert "HttpBootstrapSecret" not in transient_writer
    assert "Write-TicketboxInitdbPasswordFileAtomically" in transient_writer
    assert "Invoke-TicketboxIcaclsChecked" not in transient_writer
    dispatch = install.index("[void](Initialize-PgClusterIfNeeded -InitdbInvoker")
    runtime_binding = install.index("Initialize-TicketboxRuntimeDataBinding", dispatch)
    disposition = install.index("$c07Disposition =", runtime_binding)
    dispatch_composition = install[dispatch:disposition]
    assert dispatch < runtime_binding
    assert "[void](Initialize-PgClusterIfNeeded -InitdbInvoker" in dispatch_composition
    assert "$superPassword" not in dispatch_composition
    assert "Set-TicketboxC07DatabaseAuthorityCredential" not in dispatch_composition
    prepare_dispatch = install[
        install.index("[void](Prepare-DatabaseIfNeeded", disposition) : install.index(
            "$c07Migration =", disposition
        )
    ]
    assert "-BootstrapState" not in prepare_dispatch
    runtime_ready = install[
        install.index('if ($c07Disposition -ceq "runtime_ready")', disposition) : install.index(
            "else {", disposition
        )
    ]
    assert "Set-TicketboxC07DatabaseAuthorityCredential" not in runtime_ready
    assert "ConvertTo-TicketboxC07InstalledSecureString" in runtime_ready
    migration = install[
        install.index("function Invoke-TicketboxC07InstalledReleaseMigration") : install.index(
            "function Write-TicketboxC07InstalledRuntimeEnvironment"
        )
    ]
    assert "Invoke-TicketboxC07RecoveredSuperuserAction" in migration
    assert "Invoke-TicketboxInterruptedInitdbServiceRecovery" in prepare
    assert "中断 initdb 回执对应的同名 PostgreSQL 服务 executable 不匹配" in prepare
    assert "Invoke-TicketboxInitdbServiceUninstallRecovery" in uninstall
    assert "同名 PostgreSQL 服务 executable 不匹配" in uninstall


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL normalization contract")
def test_initdb_password_read_acl_accepts_only_windows_synchronize_normalization(
    tmp_path: Path,
) -> None:
    safety = INSTALLATION_SAFETY_SCRIPT.read_text(encoding="utf-8-sig")
    exact_rights = safety[
        safety.index("function Test-TicketboxExactAllowFileSystemRights") : safety.index(
            "function New-TicketboxInitdbPasswordFileSecurity"
        )
    ]
    assert "[Security.AccessControl.FileSystemRights]::Synchronize" in exact_rights
    password_acl = safety[
        safety.index("function Assert-TicketboxInitdbPasswordFileAcl") : safety.index(
            "function Remove-TicketboxInitdbPasswordFileExact"
        )
    ]
    assert "Test-TicketboxExactAllowFileSystemRights" in password_acl
    assert "$rule.IsInherited -or" in password_acl
    assert (
        "$rule.AccessControlType -ne\n"
        "                [Security.AccessControl.AccessControlType]::Allow -or"
        in password_acl
    )
    assert (
        "$rule.InheritanceFlags -ne\n"
        "                [Security.AccessControl.InheritanceFlags]::None -or"
        in password_acl
    )
    assert (
        "$rule.PropagationFlags -ne\n"
        "                [Security.AccessControl.PropagationFlags]::None"
        in password_acl
    )
    assert 'throw "initdb 临时密码文件含有重复授权规则。"' in password_acl
    assert 'throw "initdb 临时密码文件含有未授权账户。"' in password_acl

    for index, engine in enumerate(_powershell_engines()):
        root = tmp_path / f"initdb ACL 中文 space {index}"
        root.mkdir()
        target = root / "password probe"
        script = tmp_path / f"initdb-acl-normalization-{index}.ps1"
        _write_ps1(
            script,
            rf"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(INSTALLATION_SAFETY_SCRIPT)}'
$target = '{_ps_literal(target)}'
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$usersSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-545')
$security = New-Object Security.AccessControl.FileSecurity
$security.SetAccessRuleProtection($true, $false)
$security.SetOwner($ownerSid)
$security.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $ownerSid,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.AccessControlType]::Allow
)))
$security.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $usersSid,
    [Security.AccessControl.FileSystemRights]::Read,
    [Security.AccessControl.AccessControlType]::Allow
)))
$stream = New-TicketboxProtectedFileStream -Path $target -Security $security
try {{
    $stream.WriteByte(1)
    $stream.Flush($true)
}}
finally {{ $stream.Dispose() }}
try {{
    $acl = Get-TicketboxPathAcl $target
    $rules = @($acl.Access | Where-Object {{
        $_.IdentityReference.Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value -ceq $usersSid.Value
    }})
    if ($rules.Count -ne 1) {{ throw 'real ACL did not retain one Users allow ACE' }}
    $actual = $rules[0].FileSystemRights
    $expected =
        [Security.AccessControl.FileSystemRights]::Read -bor
        [Security.AccessControl.FileSystemRights]::Synchronize
    if ([int64]$actual -ne [int64]$expected) {{
        throw "Windows did not normalize Read to Read+Synchronize: $actual"
    }}
    if (-not (Test-TicketboxExactAllowFileSystemRights $actual `
        ([Security.AccessControl.FileSystemRights]::Read))) {{
        throw 'documented Read+Synchronize allow ACE was rejected'
    }}
    if (Test-TicketboxExactAllowFileSystemRights $actual `
        ([Security.AccessControl.FileSystemRights]::ReadAndExecute)) {{
        throw 'Read+Synchronize was widened to ReadAndExecute'
    }}
    if (Test-TicketboxExactAllowFileSystemRights $actual `
        ([Security.AccessControl.FileSystemRights]::Write)) {{
        throw 'Read+Synchronize was widened to Write'
    }}
    if (Test-TicketboxExactAllowFileSystemRights `
        ([Security.AccessControl.FileSystemRights]::Read) `
        ([Security.AccessControl.FileSystemRights]::Read)) {{
        throw 'an unnormalized allow ACE was accepted'
    }}
}}
finally {{ Remove-Item -LiteralPath $target -Force -ErrorAction Stop }}
""",
        )
        result = _run_ps1(engine, script)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows exact-delete contract")
def test_interrupted_initdb_pgdata_delete_rechecks_runtime_and_poison(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(_powershell_engines()):
        root = tmp_path / f"guard-{index}"
        script = tmp_path / f"guard-{index}.ps1"
        _write_ps1(
            script,
            rf"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SERVICE_LIFECYCLE_SCRIPT)}'
. '{_ps_literal(INSTALLATION_SAFETY_SCRIPT)}'
$dataRoot = '{_ps_literal(root)}'
$pgData = Join-Path $dataRoot 'pgdata'
$envPath = Join-Path $dataRoot 'app\.env'
$installDir = 'C:\Program Files\Ticketbox'
$receipt = [pscustomobject]@{{ pg_data = $pgData }}
$executables = @(
    'C:\Program Files\Ticketbox\pg\bin\pg_ctl.exe',
    'C:\Program Files\Ticketbox\pg\bin\postgres.exe',
    'C:\Program Files\Ticketbox\shawl\shawl.exe',
    'C:\Program Files\Ticketbox\pg\bin\initdb.exe'
)
$script:runtimeChecks = 0
$script:blockRuntime = $false
$script:blockRuntimeOnCheck = 0
$script:expectedExecutableContract = $executables -join [char]31
function Assert-TicketboxDataRootMarker {{ param($DataRoot,$InstallDir) }}
function Get-TicketboxListeningProcessIds {{
    param([int]$Port)
    if ($Port -ne 5440) {{ throw "runtime port drifted: $Port" }}
    return @()
}}
function Get-TicketboxExpectedRuntimeProcessIds {{
    param(
        [string[]]$ExpectedExecutables,
        [scriptblock]$ProcessSnapshotReader
    )
    if (($ExpectedExecutables -join [char]31) -cne $script:expectedExecutableContract) {{
        throw 'runtime executable contract drifted'
    }}
    $script:runtimeChecks += 1
    if (
        $script:blockRuntime -or
        (
            $script:blockRuntimeOnCheck -gt 0 -and
            $script:runtimeChecks -ge $script:blockRuntimeOnCheck
        )
    ) {{
        return @([int]7331)
    }}
    return @()
}}
function Reset-PgData {{
    if (Test-Path -LiteralPath $dataRoot) {{
        Remove-Item -LiteralPath $dataRoot -Recurse -Force
    }}
    New-Item -ItemType Directory -Path $pgData -Force | Out-Null
    New-Item -ItemType Directory -Path (Split-Path -Parent $envPath) -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $pgData 'partial'), 'x')
}}
Reset-PgData
[IO.File]::WriteAllText($envPath, 'DATABASE_URL=poison')
$envRejected = $false
try {{
    Remove-TicketboxInterruptedInitdbPgDataExact `
        -Receipt $receipt -PgData $pgData -EnvPath $envPath `
        -DataRoot $dataRoot -InstallDir $installDir `
        -ServiceName 'TicketboxPg' -RuntimePort 5440 `
        -ExpectedRuntimeExecutables $executables
}}
catch {{ $envRejected = $true }}
if (-not $envRejected -or -not (Test-Path -LiteralPath $pgData)) {{
    throw '.env poison was mutated or accepted'
}}
Remove-Item -LiteralPath $envPath -Force
[IO.File]::WriteAllText((Join-Path $pgData 'postmaster.pid'), '42')
$pidRejected = $false
try {{
    Remove-TicketboxInterruptedInitdbPgDataExact `
        -Receipt $receipt -PgData $pgData -EnvPath $envPath `
        -DataRoot $dataRoot -InstallDir $installDir `
        -ServiceName 'TicketboxPg' -RuntimePort 5440 `
        -ExpectedRuntimeExecutables $executables
}}
catch {{ $pidRejected = $true }}
if (-not $pidRejected -or -not (Test-Path -LiteralPath $pgData)) {{
    throw 'postmaster.pid poison was mutated or accepted'
}}
Remove-Item -LiteralPath (Join-Path $pgData 'postmaster.pid') -Force
$script:blockRuntime = $true
$script:runtimeChecks = 0
$runtimeRejected = $false
$runtimeMessage = ''
try {{
    Remove-TicketboxInterruptedInitdbPgDataExact `
        -Receipt $receipt -PgData $pgData -EnvPath $envPath `
        -DataRoot $dataRoot -InstallDir $installDir `
        -ServiceName 'TicketboxPg' -RuntimePort 5440 `
        -ExpectedRuntimeExecutables $executables
}}
catch {{
    $runtimeRejected = $true
    $runtimeMessage = $_.Exception.Message
}}
if (
    -not $runtimeRejected -or
    -not $runtimeMessage.Contains('Windows 服务 TicketboxPg 缺失') -or
    -not (Test-Path -LiteralPath $pgData)
) {{
    throw 'runtime poison was mutated or accepted'
}}
$script:blockRuntime = $false

# The first scan passes. The captured reader exposes the runtime only during
# the production root-handle callback. Swallowing that callback exception must
# make this test fail because the exact tree and sentinel would be deleted.
$script:blockRuntimeOnCheck = 2
$script:runtimeChecks = 0
$sentinel = Join-Path $pgData 'callback-sentinel.bin'
$sentinelBytes = [byte[]](0, 1, 2, 127, 128, 254, 255)
[IO.File]::WriteAllBytes($sentinel, $sentinelBytes)
Initialize-TicketboxExactTreeDeleteNativeMethods
$identityBefore = @(
    [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($pgData)
)
$contentBefore = [Convert]::ToBase64String([IO.File]::ReadAllBytes($sentinel))
$callbackRejected = $false
$callbackMessage = ''
try {{
    Remove-TicketboxInterruptedInitdbPgDataExact `
        -Receipt $receipt -PgData $pgData -EnvPath $envPath `
        -DataRoot $dataRoot -InstallDir $installDir `
        -ServiceName 'TicketboxPg' -RuntimePort 5440 `
        -ExpectedRuntimeExecutables $executables
}}
catch {{
    $callbackRejected = $true
    $callbackMessage = $_.Exception.Message
}}
if (
    -not $callbackRejected -or
    -not $callbackMessage.Contains('Windows 服务 TicketboxPg 缺失') -or
    $script:runtimeChecks -ne 2 -or
    -not (Test-Path -LiteralPath $pgData -PathType Container) -or
    -not (Test-Path -LiteralPath $sentinel -PathType Leaf)
) {{
    throw "production callback runtime poison was mutated or accepted: $callbackMessage"
}}
$identityAfter = @(
    [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($pgData)
)
$contentAfter = [Convert]::ToBase64String([IO.File]::ReadAllBytes($sentinel))
if (
    $identityAfter.Count -ne 2 -or
    [string]$identityAfter[0] -cne [string]$identityBefore[0] -or
    [string]$identityAfter[1] -cne [string]$identityBefore[1] -or
    $contentAfter -cne $contentBefore
) {{
    throw 'production callback failure changed pgdata identity or bytes'
}}

$script:blockRuntimeOnCheck = 0
$script:runtimeChecks = 0
Remove-TicketboxInterruptedInitdbPgDataExact `
    -Receipt $receipt -PgData $pgData -EnvPath $envPath `
    -DataRoot $dataRoot -InstallDir $installDir `
    -ServiceName 'TicketboxPg' -RuntimePort 5440 `
    -ExpectedRuntimeExecutables $executables
if ((Test-Path -LiteralPath $pgData) -or $script:runtimeChecks -ne 2) {{
    throw 'safe delete did not recheck runtime at the native root-handle boundary'
}}
if (Test-Path -LiteralPath $dataRoot) {{
    Remove-Item -LiteralPath $dataRoot -Recurse -Force
}}
""",
        )
        result = _run_ps1(engine, script, timeout=60)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows child-scope callback contract")
def test_runtime_absent_factory_survives_child_scope_and_native_callback(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(_powershell_engines()):
        case_root = tmp_path / f"child-scope-{index}-中文 空格"
        case_root.mkdir()
        data_root = case_root / "数据 根目录"
        subject = case_root / "subject 回调.ps1"
        driver = case_root / "driver 驱动.ps1"
        _write_ps1(
            subject,
            rf"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. '{_ps_literal(SERVICE_LIFECYCLE_SCRIPT)}'
. '{_ps_literal(INSTALLATION_SAFETY_SCRIPT)}'
$dataRoot = '{_ps_literal(data_root)}'
$pgData = Join-Path $dataRoot 'pgdata'
$sentinel = Join-Path $pgData 'sentinel-保留.bin'
$expectedExecutables = [string[]]@(
    [IO.Path]::Combine($dataRoot, '安装 路径', 'pg', 'bin', 'pg_ctl.exe'),
    [IO.Path]::Combine($dataRoot, '安装 路径', 'pg', 'bin', 'postgres.exe'),
    [IO.Path]::Combine($dataRoot, '安装 路径', 'shawl', 'shawl.exe'),
    [IO.Path]::Combine($dataRoot, '安装 路径', 'pg', 'bin', 'initdb.exe')
)
$expectedContract = $expectedExecutables -join [char]31
[AppDomain]::CurrentDomain.SetData('TicketboxGuardExpected', $expectedContract)
[AppDomain]::CurrentDomain.SetData('TicketboxGuardListenerChecks', 0)
[AppDomain]::CurrentDomain.SetData('TicketboxGuardRuntimeChecks', 0)
[AppDomain]::CurrentDomain.SetData('TicketboxGuardPoison', $false)

function Get-TicketboxListeningProcessIds {{
    param([int]$Port)
    if ($Port -ne 5440) {{ throw "runtime port drifted: $Port" }}
    $checks = [int][AppDomain]::CurrentDomain.GetData(
        'TicketboxGuardListenerChecks'
    ) + 1
    [AppDomain]::CurrentDomain.SetData('TicketboxGuardListenerChecks', $checks)
    return @()
}}
function Get-TicketboxExpectedRuntimeProcessIds {{
    param(
        [string[]]$ExpectedExecutables,
        [scriptblock]$ProcessSnapshotReader
    )
    $actual = $ExpectedExecutables -join [char]31
    $expected = [string][AppDomain]::CurrentDomain.GetData(
        'TicketboxGuardExpected'
    )
    if ($actual -cne $expected) {{ throw 'runtime executable contract drifted' }}
    $checks = [int][AppDomain]::CurrentDomain.GetData(
        'TicketboxGuardRuntimeChecks'
    ) + 1
    [AppDomain]::CurrentDomain.SetData('TicketboxGuardRuntimeChecks', $checks)
    if ([bool][AppDomain]::CurrentDomain.GetData('TicketboxGuardPoison')) {{
        return @([int]7331)
    }}
    return @()
}}

$guard = New-TicketboxRuntimeAbsentAssertion `
    -Name 'TicketboxPg' `
    -RuntimePort 5440 `
    -ExpectedRuntimeExecutables $expectedExecutables
$expectedExecutables[0] = [IO.Path]::Combine(
    $dataRoot,
    'mutated-after-factory.exe'
)

# Any dynamic lookup after factory construction now fails deterministically.
function Assert-TicketboxRuntimeAbsent {{ throw 'late Assert lookup' }}
function Get-TicketboxListeningProcessIds {{ throw 'late listener lookup' }}
function Get-TicketboxExpectedRuntimeProcessIds {{ throw 'late runtime lookup' }}

New-Item -ItemType Directory -Path $pgData -Force | Out-Null
$sentinelBytes = [byte[]](0, 1, 2, 127, 128, 254, 255)
[IO.File]::WriteAllBytes($sentinel, $sentinelBytes)
Initialize-TicketboxExactTreeDeleteNativeMethods
$identityBefore = @(
    [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($pgData)
)
$contentBefore = [Convert]::ToBase64String([IO.File]::ReadAllBytes($sentinel))

& $guard
if (
    [int][AppDomain]::CurrentDomain.GetData('TicketboxGuardListenerChecks') -ne 1 -or
    [int][AppDomain]::CurrentDomain.GetData('TicketboxGuardRuntimeChecks') -ne 1
) {{
    throw 'preflight did not execute exactly one live runtime scan'
}}

$deleteCallback = {{
    param($GuardedPath)
    & $guard
}}.GetNewClosure()
[AppDomain]::CurrentDomain.SetData('TicketboxGuardPoison', $true)
$runtimeRejected = $false
$runtimeMessage = ''
try {{
    Remove-TicketboxDataRootExact `
        -Path $pgData `
        -OnRootHandleAcquired $deleteCallback
}}
catch {{
    $runtimeRejected = $true
    $runtimeMessage = $_.Exception.Message
}}
if (
    -not $runtimeRejected -or
    -not $runtimeMessage.Contains('Windows 服务 TicketboxPg 缺失') -or
    -not (Test-Path -LiteralPath $pgData -PathType Container) -or
    -not (Test-Path -LiteralPath $sentinel -PathType Leaf)
) {{
    throw "root-handle runtime poison was mutated or accepted: $runtimeMessage"
}}
$identityAfter = @(
    [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($pgData)
)
$contentAfter = [Convert]::ToBase64String([IO.File]::ReadAllBytes($sentinel))
if (
    $identityAfter.Count -ne 2 -or
    [string]$identityAfter[0] -cne [string]$identityBefore[0] -or
    [string]$identityAfter[1] -cne [string]$identityBefore[1] -or
    $contentAfter -cne $contentBefore -or
    [int][AppDomain]::CurrentDomain.GetData('TicketboxGuardListenerChecks') -ne 2 -or
    [int][AppDomain]::CurrentDomain.GetData('TicketboxGuardRuntimeChecks') -ne 2
) {{
    throw 'runtime poison changed bytes/identity or skipped the callback rescan'
}}

[AppDomain]::CurrentDomain.SetData('TicketboxGuardPoison', $false)
Remove-TicketboxDataRootExact `
    -Path $pgData `
    -OnRootHandleAcquired $deleteCallback
if (
    (Test-Path -LiteralPath $pgData) -or
    [int][AppDomain]::CurrentDomain.GetData('TicketboxGuardListenerChecks') -ne 3 -or
    [int][AppDomain]::CurrentDomain.GetData('TicketboxGuardRuntimeChecks') -ne 3
) {{
    throw 'reused closure did not rescan and complete the safe exact delete'
}}
if (Test-Path -LiteralPath $dataRoot) {{
    Remove-Item -LiteralPath $dataRoot -Recurse -Force
}}
""",
        )
        _write_ps1(
            driver,
            rf"""
$ErrorActionPreference = 'Stop'
& '{_ps_literal(subject)}'
""",
        )
        result = _run_ps1(engine, driver, timeout=120)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_interrupted_initdb_exact_delete_uses_one_bound_runtime_guard() -> None:
    lifecycle = SERVICE_LIFECYCLE_SCRIPT.read_text(encoding="utf-8-sig")
    safety = INSTALLATION_SAFETY_SCRIPT.read_text(encoding="utf-8-sig")
    factory_start = lifecycle.index("function New-TicketboxRuntimeAbsentAssertion")
    factory_end = lifecycle.index("function Wait-TicketboxServiceSettledState", factory_start)
    factory = lifecycle[factory_start:factory_end]
    assert '"Assert-TicketboxRuntimeAbsent"' in factory
    assert '"Get-TicketboxListeningProcessIds"' in factory
    assert '"Get-TicketboxExpectedRuntimeProcessIds"' in factory
    assert "-CommandType Function" in factory
    assert "$commands.Count -ne 1" in factory
    assert "[Management.Automation.FunctionInfo]" in factory
    assert "$boundExpectedExecutables = [string[]]@(" in factory
    assert "-ListenerReader $listenerReader" in factory
    assert "-RuntimeProcessReader $runtimeProcessReader" in factory
    assert factory.count(".GetNewClosure()") == 3

    delete_start = safety.index("function Remove-TicketboxInterruptedInitdbPgDataExact")
    delete_end = safety.index("function Assert-TicketboxRecoverableInheritedFileAcl", delete_start)
    delete = safety[delete_start:delete_end]
    assert delete.count("New-TicketboxRuntimeAbsentAssertion") == 1
    assert delete.index("$runtimeAbsentGuard = New-TicketboxRuntimeAbsentAssertion") < delete.index(
        "$deleteGuard = {"
    )
    factory_call_end = delete.index("& $runtimeAbsentGuard")
    factory_call = delete[:factory_call_end]
    assert "-Name $ServiceName `" in factory_call
    assert "-RuntimePort $RuntimePort `" in factory_call
    assert "-ExpectedRuntimeExecutables $ExpectedRuntimeExecutables" in factory_call
    assert delete.count("& $runtimeAbsentGuard") == 2
    assert "Assert-TicketboxRuntimeAbsent `" not in delete
    guard_start = delete.index("$deleteGuard = {")
    guard_end = delete.index("Remove-TicketboxDataRootExact", guard_start)
    guard = delete[guard_start:guard_end]
    assert "New-TicketboxRuntimeAbsentAssertion" not in guard
    assert guard.count("& $runtimeAbsentGuard") == 1
    assert "}.GetNewClosure()" in guard
    opened_identity = guard.index("$openedIdentity = @(")
    poison_check = guard.index(
        "[TicketboxExactTreeDeleteNativeMethods]::InspectEntry($EnvPath)"
    )
    path_rejection = guard.index(
        'throw "中断 initdb PgData 句柄与已验证目标不一致。"'
    )
    identity_rejection = guard.index(
        'throw "中断 initdb PgData 身份在删除前发生变化。"'
    )
    poison_rejection = guard.index(
        'throw "中断 initdb 删除边界出现 .env 或 postmaster.pid。"'
    )
    runtime_recheck = guard.index("& $runtimeAbsentGuard")
    assert path_rejection < opened_identity < identity_rejection
    assert identity_rejection < poison_check < poison_rejection < runtime_recheck
    assert "-OnRootHandleAcquired $deleteGuard" in delete


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
def test_existing_cluster_never_invokes_fresh_initdb_callback(tmp_path: Path) -> None:
    pg_data = tmp_path / "pgdata"
    pg_data.mkdir()
    (pg_data / "PG_VERSION").write_text("17\n", encoding="ascii")
    app_data = tmp_path / "app"
    app_data.mkdir()
    harness = tmp_path / "existing-cluster-initdb-poison.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(DATABASE_SCRIPT)}'
$DataRoot = '{_ps_literal(tmp_path)}'
$PgData = '{_ps_literal(pg_data)}'
$AppData = '{_ps_literal(app_data)}'
$EnvPath = Join-Path $AppData '.env'
$PgBin = Join-Path $DataRoot 'pg-bin'
function Get-TicketboxPathEntryKindNoFollow {{ param($Path) if (Test-Path -LiteralPath $Path -PathType Leaf) {{ return 'File' }}; if (Test-Path -LiteralPath $Path -PathType Container) {{ return 'Directory' }}; return 'Missing' }}
function Read-EnvMap {{ param($Path) return @{{ DATABASE_URL = 'postgresql://ticketbox:secret@127.0.0.1:5440/ticketbox' }} }}
function Set-TicketboxPostgresInstallerConfiguration {{ $script:configured += 1 }}
function Write-Ok {{ param($Message) }}
$script:configured = 0
$script:initdbCalls = 0
$poison = {{
    param($BootstrapState)
    $script:initdbCalls += 1
    throw 'existing cluster invoked fresh initdb callback'
}}
$result = Initialize-PgClusterIfNeeded -InitdbInvoker $poison
if ($null -ne $result -or $script:initdbCalls -ne 0 -or $script:configured -ne 1) {{
    throw 'existing cluster did not take the verified no-initdb path'
}}
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
try { Initialize-PgClusterIfNeeded | Out-Null }
catch {
    $partialFailed = $true
    if ($_.Exception.Data['TicketboxInstallPublicFailureCode'] -cne
        'postgres_cluster_initialization_failed') {
        throw 'initdb failure lost its bounded public classification'
    }
}
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
def test_inherited_bootstrap_acl_repair_is_bounded_and_fail_closed(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(_powershell_engines()):
        root = tmp_path / f"acl-repair-{index}"
        root.mkdir()
        harness = root / "bootstrap-acl-repair.ps1"
        script = r"""
$ErrorActionPreference = 'Stop'
. '__INSTALLATION_SAFETY__'
. '__DATABASE_SCRIPT__'

$SecretByteCount = 32
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:PostgresBootstrapAclAccounts = @($currentAccount)
$script:PostgresBootstrapAclOwnerAccount = $currentAccount
$encoding = [Text.Encoding]::ASCII

function Get-AclShape([string]$Path) {
    $acl = Get-TicketboxPathAcl $Path
    $rules = @($acl.Access | ForEach-Object {
        [string]::Join(':', @(
            $_.IdentityReference.Translate(
                [Security.Principal.SecurityIdentifier]
            ).Value,
            [string]$_.AccessControlType,
            [string][int64]$_.FileSystemRights,
            [string]$_.InheritanceFlags,
            [string]$_.PropagationFlags,
            [string]$_.IsInherited
        ))
    } | Sort-Object)
    return [string]::Join('|', @(
        $acl.Owner,
        [string]$acl.AreAccessRulesProtected,
        ($rules -join ',')
    ))
}

function New-InheritedRecoveryCase {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Payload
    )
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $Root `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
    $app = Join-Path $Root 'app'
    New-Item -ItemType Directory -Path $app | Out-Null
    $path = Join-Path $app $script:PostgresBootstrapRecoveryFileName
    [IO.File]::WriteAllText($path, $Payload, $encoding)
    return [pscustomobject]@{
        DataRoot = $Root
        AppData = $app
        Path = $path
    }
}

$state = New-PostgresBootstrapRecoveryState
$payload = ConvertTo-PostgresBootstrapRecoveryPayload $state
$accepted = New-InheritedRecoveryCase `
    -Root (Join-Path '__ROOT__' 'accepted') `
    -Payload $payload
$script:DataRoot = $accepted.DataRoot
$script:AppData = $accepted.AppData
$beforeBytes = [IO.File]::ReadAllBytes($accepted.Path)
$acceptedRootShape = Get-AclShape $accepted.DataRoot
$acceptedAppShape = Get-AclShape $accepted.AppData
$beforeDirectoryAcl = Get-TicketboxPathAcl $accepted.AppData
$beforeFileAcl = Get-TicketboxPathAcl $accepted.Path
if ($beforeDirectoryAcl.AreAccessRulesProtected -or
    $beforeFileAcl.AreAccessRulesProtected -or
    @($beforeDirectoryAcl.Access | Where-Object { -not $_.IsInherited }).Count -ne 0 -or
    @($beforeFileAcl.Access | Where-Object { -not $_.IsInherited }).Count -ne 0) {
    throw 'accepted precondition was not an exact inherited ACL chain'
}
if (-not (Repair-PostgresBootstrapRecoveryFileAcl)) {
    throw 'exact inherited bootstrap ACL was not repaired'
}
$afterBytes = [IO.File]::ReadAllBytes($accepted.Path)
if (-not (Test-TicketboxByteArrayEquals $beforeBytes $afterBytes)) {
    throw 'bootstrap ACL repair changed recovery bytes'
}
if ((Get-AclShape $accepted.DataRoot) -cne $acceptedRootShape -or
    (Get-AclShape $accepted.AppData) -cne $acceptedAppShape) {
    throw 'bootstrap ACL repair changed its validated parent ACL chain'
}
$roundTrip = Read-PostgresBootstrapRecoveryState
if ($roundTrip.SuperuserPassword -cne $state.SuperuserPassword -or
    $roundTrip.RolePassword -cne $state.RolePassword -or
    $roundTrip.HttpBootstrapSecret -cne $state.HttpBootstrapSecret) {
    throw 'bootstrap ACL repair changed recovery authority'
}
if (Repair-PostgresBootstrapRecoveryFileAcl) {
    throw 'protected bootstrap ACL did not converge idempotently'
}

$parentAccounts = @($currentAccount, 'BUILTIN\Users')
Set-TicketboxExactDirectoryAcl `
    -Path $accepted.AppData `
    -Accounts $parentAccounts `
    -OwnerAccount $currentAccount `
    -Recurse
$normalizedAcl = Get-TicketboxPathAcl $accepted.Path
if ($normalizedAcl.AreAccessRulesProtected -or
    @($normalizedAcl.Access | Where-Object { $_.IsInherited }).Count -ne 2) {
    throw 'AppData recursive normalization did not expose the expected inherited test shape'
}
if (-not (Protect-PostgresBootstrapRecoveryFileAfterAclNormalization `
    -ParentFullControlAccounts $parentAccounts)) {
    throw 'post-normalization bootstrap ACL was not re-protected'
}
if (-not (Test-TicketboxByteArrayEquals `
    $beforeBytes `
    ([IO.File]::ReadAllBytes($accepted.Path)))) {
    throw 'post-normalization bootstrap protection changed recovery bytes'
}
[void](Read-PostgresBootstrapRecoveryState)
if (Protect-PostgresBootstrapRecoveryFileAfterAclNormalization `
    -ParentFullControlAccounts $parentAccounts) {
    throw 'post-normalization bootstrap protection was not idempotent'
}

$malformedSentinel = 'malformed-bootstrap-secret-sentinel'
$malformed = New-InheritedRecoveryCase `
    -Root (Join-Path '__ROOT__' 'malformed') `
    -Payload $malformedSentinel
$script:DataRoot = $malformed.DataRoot
$script:AppData = $malformed.AppData
$malformedBeforeBytes = [IO.File]::ReadAllBytes($malformed.Path)
$malformedRootShape = Get-AclShape $malformed.DataRoot
$malformedAppShape = Get-AclShape $malformed.AppData
$malformedFileShape = Get-AclShape $malformed.Path
$malformedRejected = $false
try { Repair-PostgresBootstrapRecoveryFileAcl | Out-Null }
catch {
    $malformedRejected = $true
    if ($_.Exception.Message.Contains($malformedSentinel)) {
        throw 'malformed bootstrap payload leaked through repair error'
    }
}
$malformedAfterAcl = Get-TicketboxPathAcl $malformed.Path
if (-not $malformedRejected -or $malformedAfterAcl.AreAccessRulesProtected -or
    (Get-AclShape $malformed.DataRoot) -cne $malformedRootShape -or
    (Get-AclShape $malformed.AppData) -cne $malformedAppShape -or
    (Get-AclShape $malformed.Path) -cne $malformedFileShape -or
    -not (Test-TicketboxByteArrayEquals `
        $malformedBeforeBytes `
        ([IO.File]::ReadAllBytes($malformed.Path)))) {
    throw 'malformed inherited bootstrap payload was mutated or accepted'
}

$unsafe = New-InheritedRecoveryCase `
    -Root (Join-Path '__ROOT__' 'unsafe-acl') `
    -Payload $payload
$script:DataRoot = $unsafe.DataRoot
$script:AppData = $unsafe.AppData
$unsafeBeforeBytes = [IO.File]::ReadAllBytes($unsafe.Path)
& icacls.exe $unsafe.Path /grant '*S-1-1-0:R' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'failed to seed explicit unsafe ACL' }
$unsafeBeforeAcl = Get-TicketboxPathAcl $unsafe.Path
$unsafeRootShape = Get-AclShape $unsafe.DataRoot
$unsafeAppShape = Get-AclShape $unsafe.AppData
$unsafeFileShape = Get-AclShape $unsafe.Path
if ($unsafeBeforeAcl.AreAccessRulesProtected -or
    @($unsafeBeforeAcl.Access | Where-Object { -not $_.IsInherited }).Count -ne 1) {
    throw 'unsafe ACL precondition was not established'
}
$unsafeRejected = $false
try { Repair-PostgresBootstrapRecoveryFileAcl | Out-Null }
catch { $unsafeRejected = $true }
$unsafeAfterAcl = Get-TicketboxPathAcl $unsafe.Path
if (-not $unsafeRejected -or $unsafeAfterAcl.AreAccessRulesProtected -or
    @($unsafeAfterAcl.Access | Where-Object { -not $_.IsInherited }).Count -ne 1 -or
    (Get-AclShape $unsafe.DataRoot) -cne $unsafeRootShape -or
    (Get-AclShape $unsafe.AppData) -cne $unsafeAppShape -or
    (Get-AclShape $unsafe.Path) -cne $unsafeFileShape -or
    -not (Test-TicketboxByteArrayEquals `
        $unsafeBeforeBytes `
        ([IO.File]::ReadAllBytes($unsafe.Path)))) {
    throw 'unsafe inherited bootstrap ACL was mutated or accepted'
}

$postMalformed = New-InheritedRecoveryCase `
    -Root (Join-Path '__ROOT__' 'post-normalization-malformed') `
    -Payload $malformedSentinel
$script:DataRoot = $postMalformed.DataRoot
$script:AppData = $postMalformed.AppData
Set-TicketboxExactDirectoryAcl `
    -Path $postMalformed.AppData `
    -Accounts $parentAccounts `
    -OwnerAccount $currentAccount `
    -Recurse
$postMalformedRootShape = Get-AclShape $postMalformed.DataRoot
$postMalformedAppShape = Get-AclShape $postMalformed.AppData
$postMalformedFileShape = Get-AclShape $postMalformed.Path
$postMalformedBytes = [IO.File]::ReadAllBytes($postMalformed.Path)
$postMalformedRejected = $false
try {
    Protect-PostgresBootstrapRecoveryFileAfterAclNormalization `
        -ParentFullControlAccounts $parentAccounts | Out-Null
}
catch {
    $postMalformedRejected = $true
    if ($_.Exception.Message.Contains($malformedSentinel)) {
        throw 'post-normalization malformed payload leaked through repair error'
    }
}
if (-not $postMalformedRejected -or
    (Get-AclShape $postMalformed.DataRoot) -cne $postMalformedRootShape -or
    (Get-AclShape $postMalformed.AppData) -cne $postMalformedAppShape -or
    (Get-AclShape $postMalformed.Path) -cne $postMalformedFileShape -or
    -not (Test-TicketboxByteArrayEquals `
        $postMalformedBytes `
        ([IO.File]::ReadAllBytes($postMalformed.Path)))) {
    throw 'post-normalization malformed payload was mutated or accepted'
}

$postUnsafe = New-InheritedRecoveryCase `
    -Root (Join-Path '__ROOT__' 'post-normalization-unsafe') `
    -Payload $payload
$script:DataRoot = $postUnsafe.DataRoot
$script:AppData = $postUnsafe.AppData
Set-TicketboxExactDirectoryAcl `
    -Path $postUnsafe.AppData `
    -Accounts $parentAccounts `
    -OwnerAccount $currentAccount `
    -Recurse
& icacls.exe $postUnsafe.Path /grant '*S-1-1-0:R' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'failed to seed post-normalization unsafe ACL' }
$postUnsafeRootShape = Get-AclShape $postUnsafe.DataRoot
$postUnsafeAppShape = Get-AclShape $postUnsafe.AppData
$postUnsafeFileShape = Get-AclShape $postUnsafe.Path
$postUnsafeBytes = [IO.File]::ReadAllBytes($postUnsafe.Path)
$postUnsafeRejected = $false
try {
    Protect-PostgresBootstrapRecoveryFileAfterAclNormalization `
        -ParentFullControlAccounts $parentAccounts | Out-Null
}
catch { $postUnsafeRejected = $true }
if (-not $postUnsafeRejected -or
    (Get-AclShape $postUnsafe.DataRoot) -cne $postUnsafeRootShape -or
    (Get-AclShape $postUnsafe.AppData) -cne $postUnsafeAppShape -or
    (Get-AclShape $postUnsafe.Path) -cne $postUnsafeFileShape -or
    -not (Test-TicketboxByteArrayEquals `
        $postUnsafeBytes `
        ([IO.File]::ReadAllBytes($postUnsafe.Path)))) {
    throw 'post-normalization unsafe ACL was mutated or accepted'
}

$actual = New-InheritedRecoveryCase `
    -Root (Join-Path '__ROOT__' 'actual-set-acl') `
    -Payload $payload
$script:DataRoot = $actual.DataRoot
$script:AppData = $actual.AppData
$script:PgData = Join-Path $actual.DataRoot 'pgdata'
$script:DefaultUploadRoot = Join-Path $actual.AppData 'uploads'
$script:LogDir = Join-Path $actual.AppData 'logs'
$script:BackupDir = Join-Path $actual.AppData 'backups'
$script:InstallerState = Join-Path $actual.DataRoot 'installer-state-test'
$script:BootstrapExposureRecoveryGuardPath = Join-Path $actual.DataRoot 'missing-bootstrap-guard'
$script:InstallerRuntimeRecoveryGuardPath = Join-Path $actual.DataRoot 'missing-runtime-guard'
$script:ProgramDir = Join-Path '__ROOT__' 'program'
$script:PgHome = Join-Path '__ROOT__' 'pg-home'
$script:PgServiceName = 'TicketboxPgTest'
$script:BackendServiceName = 'TicketboxBackendTest'
[IO.File]::WriteAllText(
    (Get-TicketboxDataRootMarkerPath $actual.DataRoot),
    'test-marker',
    $encoding)
function Write-Step { param([string]$Message) }
function Write-Ok { param([string]$Message) }
function Initialize-TicketboxInstallerStateDirectory {
    param([string]$Path)
    return $Path
}
$tokens = $null
$parseErrors = $null
$installAst = [Management.Automation.Language.Parser]::ParseFile(
    '__INSTALL_SCRIPT__',
    [ref]$tokens,
    [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'install script did not parse for function extraction' }
$definitions = @($installAst.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq 'Set-TicketboxAcl'
}, $true))
if ($definitions.Count -ne 1) { throw 'Set-TicketboxAcl definition was not unique' }
Invoke-Expression $definitions[0].Extent.Text
$actualBeforeBytes = [IO.File]::ReadAllBytes($actual.Path)
Set-TicketboxAcl `
    -IncludePgService $false `
    -IncludeBackendService $false `
    -PrivilegedAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$actualAfterAcl = Get-TicketboxPathAcl $actual.Path
if (-not $actualAfterAcl.AreAccessRulesProtected -or
    @($actualAfterAcl.Access | Where-Object { $_.IsInherited }).Count -ne 0 -or
    -not (Test-TicketboxByteArrayEquals `
        $actualBeforeBytes `
        ([IO.File]::ReadAllBytes($actual.Path)))) {
    throw 'actual Set-TicketboxAcl did not re-protect bootstrap recovery bytes'
}
[void](Read-PostgresBootstrapRecoveryState)

$wired = New-InheritedRecoveryCase `
    -Root (Join-Path '__ROOT__' 'initialize-wiring') `
    -Payload $payload
$script:DataRoot = $wired.DataRoot
$script:AppData = $wired.AppData
$script:PgData = Join-Path $wired.DataRoot 'pgdata'
$script:EnvPath = Join-Path $wired.AppData '.env'
New-Item -ItemType Directory -Path $script:PgData | Out-Null
[IO.File]::WriteAllText(
    (Join-Path $script:PgData 'PG_VERSION'),
    '17',
    $encoding)
function Read-EnvMap { return @{} }
function Set-TicketboxPostgresInstallerConfiguration {
    throw 'initialize-wiring-reached-after-repair'
}
$wiredReached = $false
try { Initialize-PgClusterIfNeeded | Out-Null }
catch {
    if ($_.Exception.Message -cne 'initialize-wiring-reached-after-repair') {
        throw
    }
    $wiredReached = $true
}
if (-not $wiredReached -or
    -not (Get-TicketboxPathAcl $wired.Path).AreAccessRulesProtected) {
    throw 'Initialize-PgClusterIfNeeded bypassed inherited bootstrap ACL repair'
}
[void](Read-PostgresBootstrapRecoveryState)
"""
        replacements = {
            "__INSTALLATION_SAFETY__": _ps_literal(INSTALLATION_SAFETY_SCRIPT),
            "__DATABASE_SCRIPT__": _ps_literal(DATABASE_SCRIPT),
            "__INSTALL_SCRIPT__": _ps_literal(INSTALL_SCRIPT),
            "__ROOT__": _ps_literal(root),
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
