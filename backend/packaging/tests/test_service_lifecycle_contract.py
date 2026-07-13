import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def test_service_lifecycle_requires_exact_image_path_and_terminal_states() -> None:
    lifecycle = _read("windows_service_contract.ps1") + "\n" + _read(
        "windows_service_lifecycle.ps1"
    )

    assert "Get-CimInstance -ClassName Win32_Service" in lifecycle
    assert "ConvertTo-TicketboxServiceExecutablePath" in lifecycle
    assert "StringComparison]::OrdinalIgnoreCase" in lifecycle
    assert "拒绝操作同名外部服务" in lifecycle
    assert 'Wait-TicketboxServiceState @waitArguments -DesiredState "stopped"' in lifecycle
    assert 'Wait-TicketboxServiceState @waitArguments -DesiredState "running"' in lifecycle
    assert '-DesiredState "absent"' in lifecycle
    assert "Stop-Service -Name $Name -Force -ErrorAction Stop" in lifecycle
    assert "Restart-TicketboxOwnedServiceIfExists" in lifecycle
    assert "拒绝未加引号且含空格" in lifecycle
    assert "Assert-TicketboxServiceArgumentPath" in lifecycle
    assert "Assert-TicketboxPgServiceCommand" in lifecycle
    assert "Assert-TicketboxShawlServiceCommand" in lifecycle
    assert "Assert-TicketboxServiceAccount" in lifecycle
    assert "Wait-TicketboxServiceSettledState" in lifecycle
    assert "New-TicketboxWaitDeadline" in lifecycle
    assert "Get-TicketboxWaitAttempts" not in lifecycle
    assert "New-TicketboxPgServiceImagePath" in lifecycle
    assert "New-TicketboxShawlServiceImagePath" in lifecycle
    assert "Get-TicketboxServiceDependencies" in lifecycle
    assert "Initialize-TicketboxServiceFailurePolicyNativeMethods" in lifecycle
    assert "QueryServiceConfig2" in lifecycle
    assert "Assert-TicketboxServiceFailurePolicy" in lifecycle
    assert '"--kill-process-tree"' in lifecycle
    assert "Wait-TicketboxBackendRuntimeStopped" in lifecycle
    assert "Get-TicketboxListeningProcessIds" in lifecycle
    assert "Get-TicketboxServiceProcessId" in lifecycle
    assert "Get-TicketboxExpectedRuntimeProcessIds" in lifecycle
    assert "Get-CimInstance -ClassName Win32_Process" in lifecycle
    assert "[Environment]::SystemDirectory" in lifecycle
    assert 'Join-Path $systemDirectory "sc.exe"' in lifecycle
    assert "Test-Path -LiteralPath $scExecutable -PathType Leaf" in lifecycle
    assert "[System.IO.FileAttributes]::ReparsePoint" in lifecycle
    assert "& $scExecutable @ScArgs" in lifecycle
    assert "& sc.exe @ScArgs" not in lifecycle
    assert "Set-TicketboxOwnedServiceDemandStartIfExists" in lifecycle
    assert "Set-TicketboxOwnedServiceDelayedAutoStartIfExists" in lifecycle
    install = _read("install_bundled_services.ps1")
    prepare = _read("prepare_bundled_upgrade.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")
    recovery_cleanup = prepare[
        prepare.index("function Remove-TicketboxRecoveryPgServiceIfExists") : prepare.index(
            "function Assert-TicketboxDeferredPreservedPgServiceConfiguration"
        )
    ]
    assert "if (-not (Test-TicketboxServiceExists $PgRecoveryServiceName)) { return }" not in recovery_cleanup
    assert recovery_cleanup.index("Get-TicketboxServiceSid") < recovery_cleanup.index(
        "Assert-TicketboxRecoveryServiceAclTransition"
    )
    assert recovery_cleanup.index("Remove-TicketboxOwnedServiceIfExists") < recovery_cleanup.index(
        "Set-TicketboxRecoveryServiceDataAcl"
    )
    assert "Get-TicketboxPathEntryKindNoFollow" in recovery_cleanup
    assert "ValidateInstalledServicesOnly" in install
    assert "ExpectedBackendServiceName" in install
    validation = install[
        install.index("if ($ValidateInstalledServicesOnly)") : install.index("$operationLock =")
    ]
    assert "Assert-ExpectedServiceConfiguration $PgServiceName" in validation
    assert "Assert-ExpectedServiceConfiguration $BackendServiceName" in validation
    assert validation.count("Assert-TicketboxServiceFailurePolicy `") == 2
    assert "-ExpectedResetSeconds $ScmFailureResetSeconds" in validation
    assert "-ExpectedRestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)" in validation
    assert validation.count("Assert-TicketboxServiceDelayedAutoStart") == 2
    stopped_validation = install[
        install.index("if ($ValidateBackendRuntimeStoppedOnly)") : install.index("$operationLock =")
    ]
    assert "Wait-TicketboxBackendRuntimeStopped `" in stopped_validation
    assert "-BackendPort $BackendPort" in stopped_validation
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in stopped_validation
    for entry_script in (install, prepare, uninstall):
        assert "[int]$InstallerLockOwnerProcessId = 0" in entry_script
        assert "Enter-TicketboxLifecycleLock `" in entry_script
        assert "-ExternalOwnerProcessId $InstallerLockOwnerProcessId" in entry_script
        assert "InstallerLockHeld" not in entry_script
    lifecycle_lock = _read("windows_lifecycle_lock.ps1")
    assert "installer-operation.lock" in lifecycle_lock
    assert "Enter-TicketboxExclusiveFileLock $operationLockPath" not in lifecycle_lock
    assert "Enter-TicketboxProtectedExclusiveFileLock `" in lifecycle_lock
    assert "Operation = $operationLock" in lifecycle_lock
    assert "Get-TicketboxServiceSid" in lifecycle
    assert 'Invoke-TicketboxScChecked @("showsid", $Name)' in lifecycle
    assert "$initialAclAccounts" not in install
    stop_backend = install.index("Stop-ServiceIfExists", install.index("$hadExistingPgService"))
    isolate_acl = install.index("Set-TicketboxAcl", stop_backend)
    backup = install.index("Invoke-PreUpgradeBackupIfNeeded", isolate_acl)
    assert stop_backend < isolate_acl < backup
    assert "-IncludeBackendService $hadExistingBackendService" in install
    for runtime_contract in (install, prepare):
        assert "$ServiceBootstrapExposureRecoveryGuardPath" in runtime_contract
        assert (
            "Get-TicketboxRuntimeBootstrapRecoveryGuardPath $binding.RuntimeDataRoot"
            in runtime_contract
        )
    assert (
        "-BootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath"
        in install
    )
    assert (
        "-ExpectedBootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath"
        in prepare
    )
    acl_function = install[install.index("function Set-TicketboxAcl") : install.index("function Assert-PortAvailable")]
    assert acl_function.index("-Path $AppData") < acl_function.index(
        "Initialize-TicketboxInstallerStateDirectory $InstallerState"
    )
    assert '$markerReadAccounts += "NT SERVICE\\$BackendServiceName"' in acl_function
    marker_acl = acl_function.index("-Path (Get-TicketboxDataRootMarkerPath $DataRoot)")
    assert acl_function.index("-ReadExecuteAccounts $markerReadAccounts", marker_acl) > marker_acl
    operation = install[install.index("$operationLock =") :]
    assert operation.index("Initialize-TicketboxInstallerStateArtifacts") < operation.index(
        "Adopt-TicketboxOwnerBootstrapHandoff"
    )
    pg_registration = install[install.index("function Register-PgService") : install.index("function Register-BackendService")]
    backend_registration = install[
        install.index("function Register-BackendService") : install.index("function Invoke-IcaclsChecked")
    ]
    assert "Remove-ServiceIfExists" not in pg_registration
    assert "Remove-ServiceIfExists" not in backend_registration
    assert '"create", $PgServiceName' in pg_registration
    assert '"binPath=", $pgImagePath' in pg_registration
    assert '"obj=", "NT SERVICE\\$PgServiceName"' in pg_registration
    assert "& $PgCtl register" not in pg_registration
    assert "password=" not in pg_registration.lower()
    fresh_pg = pg_registration[pg_registration.index("else {") :]
    assert fresh_pg.index('"create", $PgServiceName') < fresh_pg.index(
        "Assert-ExpectedServiceConfiguration $PgServiceName"
    )
    assert '"create", $BackendServiceName' in backend_registration
    assert '"start=", "disabled"' in backend_registration
    assert '"start=", "demand"' not in backend_registration
    assert '"start=", "delayed-auto"' not in backend_registration
    assert 'ExpectedStartMode "Disabled"' in backend_registration
    assert '"depend=", $PgServiceName' in backend_registration

    mutation = install[install.index("$mutationStarted = $true") :]
    register_backend = mutation.index("Register-BackendService")
    write_guard = mutation.index("Write-TicketboxInstallerRuntimeRecoveryGuard")
    enable_demand = mutation.index("Set-TicketboxOwnedServiceDemandStartIfExists")
    start_backend = mutation.index('Write-Step "启动后端服务"')
    assert register_backend < write_guard < enable_demand < start_backend

    receipt = _read("windows_lifecycle_receipt.ps1")
    promotion = receipt[
        receipt.index("function Enable-TicketboxInstalledServicesAutoStart") : receipt.index(
            "function Complete-TicketboxInstalledLifecycleTransaction"
        )
    ]
    assert "Set-TicketboxOwnedServiceDelayedAutoStartIfExists" in promotion
    assert "Assert-TicketboxServiceDelayedAutoStart" in promotion

    backend_bootstrap = _read("windows_backend_bootstrap.ps1")
    restart = backend_bootstrap[
        backend_bootstrap.index("Restart-TicketboxOwnedServiceIfExists") :
        backend_bootstrap.index("Wait-BackendHealth", backend_bootstrap.index("Restart-TicketboxOwnedServiceIfExists"))
    ]
    assert "-BackendPort $BackendPort" in restart
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in restart

    database = _read("windows_bundled_database.ps1")
    assert '"-tAc", $Sql' not in database
    assert '"-p", "$PgPort", "-d", $Database, "-tA"' in database
    assert "$out = $Sql | & $psql @args 2>&1" in database
    assert '：$Sql`n$out' not in database
    assert 'throw "psql 执行失败（db=$Database, exit=$rc）。"' in database

    legacy_installer = _read("install_ticketbox.ps1")
    assert '"-tAc", $Sql' not in legacy_installer
    assert '"-d", $Database, "-tA")' in legacy_installer
    assert "$out = $Sql | & $Psql @psqlArgs 2>&1" in legacy_installer
    assert '：$Sql"' not in legacy_installer


def test_pre_upgrade_backup_uses_old_tools_before_stopping_postgres() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")

    upgrade_try = prepare.index("try {", prepare.index("$backupRequired"))
    stop_backend = prepare.index("Disable-TicketboxOwnedServiceIfExists", upgrade_try)
    dump_database = prepare.index("Invoke-TicketboxPgDumpCustom")
    verify_dump = prepare.index("& $PgRestore --list")
    stop_postgres = prepare.index("Disable-TicketboxOwnedServiceIfExists", dump_database)
    assert stop_backend < dump_database < verify_dump < stop_postgres
    backend_prepare = prepare[
        prepare.index("if ($hasBackendService) {", upgrade_try) : prepare.index(
            "if ($usingRecoveryPgService)", upgrade_try
        )
    ]
    assert "Disable-TicketboxOwnedServiceIfExists" in backend_prepare
    assert "Set-TicketboxPreparedServiceDemandStart" not in backend_prepare
    assert '$PgBin = Join-Path $InstallDir "pg\\bin"' in prepare
    assert "Restore-PreviousServiceState" in prepare
    assert "旧程序保持不变" in prepare
    assert "Assert-TicketboxConnectedPostgresDataRoot" in prepare
    assert "Get-TicketboxLocalDatabaseConnection" in prepare
    assert "Assert-ExpectedServiceConfiguration" in prepare
    assert "& $PgCtl status -D $PgData" in prepare
    assert 'Wait-TicketboxServiceSettledState -Name $PgServiceName' in prepare
    assert "InstalledReleaseConfigPath" in prepare
    assert "LifecycleReceiptPath" in prepare
    assert "Write-TicketboxLifecycleReceipt" in prepare
    assert "BackupCompleted $backupCompleted" in prepare
    assert "Assert-TicketboxReleaseIdentityCompatible" in prepare
    assert "ExpectedStopTimeoutMs = $InstalledStopTimeoutMs" in prepare
    assert "ExpectedRestartDelayMs = $InstalledRestartDelayMs" in prepare
    assert "Assert-TicketboxPgClusterStopped" in prepare
    assert "Repair-TicketboxPreflightInstallAcl" in prepare
    assert "Assert-TicketboxPortAvailableForMissingService" in prepare
    assert "-BackendPort $BackendPort" in prepare
    assert "Set-TicketboxPreparedServiceDemandStart" in prepare
    assert "files-may-have-been-replaced" in prepare
    disabled_pg = prepare.index('if ($hasPgService -and $pgStartPolicy -eq "disabled")')
    demand_start = prepare.index("Set-TicketboxPreparedServiceDemandStart", disabled_pg)
    start_pg = prepare.index("Start-TicketboxOwnedServiceIfExists", demand_start)
    assert disabled_pg < demand_start < start_pg
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in prepare

    install = _read("install_bundled_services.ps1")
    installer = _read("ticketbox-installer-flow.isph")
    assert "PreviousReleaseConfigPath" not in install
    assert "SkipPreUpgradeBackup" not in installer
    assert "Read-TicketboxLifecycleReceipt" in install
    assert "-ExpectedStopTimeoutMs $PreviousStopTimeoutMs" in install
    assert "InstalledReleaseConfigSnapshotPath" not in installer
    assert "PreviousReleaseConfigPath" not in installer
    assert "LifecycleReceiptPath" in installer


def test_pre_copy_compensation_preserves_exact_start_policy_mutation() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    lifecycle = _read("windows_service_lifecycle.ps1")

    capture = prepare.index("$backendStartPolicy = if ($hasBackendService)")
    mutation = prepare.index("$installAclMutationStarted = $true", capture)
    assert capture < mutation
    assert "Get-TicketboxServiceStartPolicy $BackendServiceName" in prepare[capture:mutation]
    assert "Get-TicketboxServiceStartPolicy $PgServiceName" in prepare[capture:mutation]
    assert "-PreviousPgStartPolicy $pgStartPolicy" in prepare
    assert "-PreviousBackendStartPolicy $backendStartPolicy" in prepare

    restore = prepare[
        prepare.index("function Restore-PreviousServiceState") : prepare.index(
            "function Initialize-LegacyInstalledServicePolicy"
        )
    ]
    assert "Set-TicketboxOwnedServiceDelayedAutoStartIfExists" not in restore
    assert restore.count("Set-TicketboxOwnedServiceStartPolicyIfExists") == 3
    restart_catch = restore.index("$restartFailure = $_.Exception.Message")
    exact_policy_restore = restore.index("$policyFailures = @()", restart_catch)
    aggregate_failure = restore.index("if ($null -ne $restartFailure", exact_policy_restore)
    assert restart_catch < exact_policy_restore < aggregate_failure
    assert '@{ Name = $PgServiceName; Executable = $PgCtl; Value = $PgStartPolicy }' in restore
    assert (
        '@{ Name = $BackendServiceName; Executable = $ShawlExe; Value = $BackendStartPolicy }'
        in restore
    )
    assert '$PgStartPolicy -eq "disabled"' in restore
    assert '$BackendStartPolicy -eq "disabled"' in restore
    assert '"manual"' in restore
    assert "Get-TicketboxServiceStartPolicy" in lifecycle
    assert "Set-TicketboxOwnedServiceStartPolicyIfExists" in lifecycle


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell service contract")
def test_service_policy_and_sid_contract_in_powershell_5_and_7(tmp_path: Path) -> None:
    harness = tmp_path / "service-start-policy.ps1"
    lifecycle = str(PACKAGING / "windows_service_lifecycle.ps1").replace("'", "''")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{lifecycle}'
$sid = Get-TicketboxServiceSid 'TicketboxPgRecoveryContractProbe'
if ($sid -cnotmatch '^S-1-5-80-(?:[0-9]+-){{4}}[0-9]+$') {{
    throw "invalid virtual service SID: $sid"
}}
$script:scModes = @()
function Assert-TicketboxServiceOwnership([string]$Name, [string]$ExpectedExecutable) {{ return $true }}
function Invoke-TicketboxScChecked([string[]]$ScArgs) {{
    $script:scModes += $ScArgs[-1]
    return ''
}}
function Assert-TicketboxServiceStartPolicy([string]$Name, [string]$ExpectedStartPolicy) {{ }}
foreach ($policy in @('disabled', 'manual', 'auto', 'delayed_auto')) {{
    Set-TicketboxOwnedServiceStartPolicyIfExists `
        -Name Demo `
        -ExpectedExecutable 'C:\\Demo\\demo.exe' `
        -StartPolicy $policy
}}
$actual = $script:scModes -join ','
if ($actual -ne 'disabled,demand,auto,delayed-auto') {{ throw "policy mapping changed: $actual" }}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows TCP cmdlet contract")
def test_tcp_listener_query_handles_native_empty_and_close_in_powershell_5_and_7(
    tmp_path: Path,
) -> None:
    flow = _read("ticketbox-installer-flow.isph")
    assert "CmdletizationQuery_NotFound,Get-NetTCPConnection" in flow
    assert "catch { exit 2 }" not in flow

    harness = tmp_path / "tcp-listener-query.ps1"
    lifecycle = str(PACKAGING / "windows_service_lifecycle.ps1").replace("'", "''")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{lifecycle}'
$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
$listener.Start()
$port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$active = @(Get-TicketboxListeningProcessIds -Port $port)
if ($active.Count -eq 0 -or $active -notcontains $PID) {{
    throw 'native listener was not reported'
}}
$listener.Stop()
$deadline = [DateTime]::UtcNow.AddSeconds(5)
do {{
    $closed = @(Get-TicketboxListeningProcessIds -Port $port)
    if ($closed.Count -eq 0) {{ break }}
    Start-Sleep -Milliseconds 50
}} while ([DateTime]::UtcNow -lt $deadline)
if ($closed.Count -ne 0) {{ throw 'closed listener was still reported' }}
$unused = @(Get-TicketboxListeningProcessIds -Port $port)
if ($unused.Count -ne 0) {{ throw 'unused port was not treated as empty' }}
$cimFailurePropagated = $false
try {{
    Get-TicketboxListeningProcessIds `
        -Port $port `
        -ConnectionReader {{
            throw [System.InvalidOperationException]::new('simulated CIM failure')
        }} | Out-Null
}}
catch {{
    $cimFailurePropagated = $_.Exception.Message -eq 'simulated CIM failure'
}}
if (-not $cimFailurePropagated) {{ throw 'real CIM failure was swallowed' }}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command-line contract")
def test_service_image_paths_roundtrip_in_powershell_5_and_7(tmp_path: Path) -> None:
    contract = PACKAGING / "windows_service_contract.ps1"
    harness = tmp_path / "service-image-roundtrip.ps1"
    harness.write_text(
        fr"""
$ErrorActionPreference = 'Stop'
. '{str(contract).replace("'", "''")}'
$pg = New-TicketboxPgServiceImagePath `
    -PgCtlPath 'C:\Program Files\Ticketbox\pg\bin\pg_ctl.exe' `
    -ServiceName TicketboxPg `
    -DataRoot 'D:\Ticketbox Data\pgdata'
$pgParts = @(Split-TicketboxWindowsCommandLine $pg)
if ($pgParts.Count -ne 7 -or $pgParts[5] -cne 'D:\Ticketbox Data\pgdata') {{
    throw 'PostgreSQL ImagePath did not roundtrip'
}}
$shawl = New-TicketboxShawlServiceImagePath `
    -ShawlPath 'C:\Program Files\Ticketbox\shawl\shawl.exe' `
    -ServiceName TicketboxBackend `
    -WorkingDirectory 'D:\Ticketbox Data\app' `
    -LogDirectory 'D:\Ticketbox Data\app\logs' `
    -BackendPath 'C:\Program Files\Ticketbox\program\ticketbox-backend\ticketbox-backend.exe' `
    -PgDumpPath 'C:\Program Files\Ticketbox\pg\bin\pg_dump.exe' `
    -PgRestorePath 'C:\Program Files\Ticketbox\pg\bin\pg_restore.exe' `
    -BootstrapRecoveryGuardPath 'D:\Ticketbox Data\bootstrap-exposure-recovery-pending' `
    -InstallerRecoveryGuardPath 'D:\Ticketbox Data\installer-runtime-recovery-pending' `
    -DataRootMarkerPath 'C:\ProgramData\TicketboxRuntimeBinding\data-root\.ticketbox-data-root.json' `
    -DataVolumeIdentity '\\?\Volume{{01234567-89AB-CDEF-0123-456789ABCDEF}}\' `
    -StopTimeoutMs 25000 `
    -RestartDelayMs 5000
$shawlParts = @(Split-TicketboxWindowsCommandLine $shawl)
if ($shawlParts[-1] -cne 'C:\Program Files\Ticketbox\program\ticketbox-backend\ticketbox-backend.exe') {{
    throw 'Shawl ImagePath did not roundtrip'
}}
if (@($shawlParts | Where-Object {{ $_ -ceq '--kill-process-tree' }}).Count -ne 1) {{
    throw 'Shawl process-tree termination flag did not roundtrip exactly once'
}}
if (@($shawlParts | Where-Object {{ $_ -ceq 'TICKETBOX_DATA_VOLUME_IDENTITY=\\?\VOLUME{{01234567-89AB-CDEF-0123-456789ABCDEF}}\' }}).Count -ne 1) {{
    throw 'Shawl Volume GUID authority did not roundtrip exactly once'
}}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_deadline_secret_cleanup_and_lock_bitness_fail_closed(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell security behavior contract")

    host_guard = """function Assert-TicketboxSupportedPowerShellHost {
    Assert-TicketboxPowerShellBitness `
        -Is64BitOperatingSystem ([Environment]::Is64BitOperatingSystem) `
        -Is64BitProcess ([Environment]::Is64BitProcess)
}"""
    assert host_guard in _read("windows_lifecycle_lock.ps1")

    def literal(path: Path) -> str:
        return str(path).replace("'", "''")

    behavior_script = tmp_path / "security-behavior.ps1"
    secret_path = tmp_path / "locked-secret.txt"
    lifecycle_lock_path = tmp_path / "installer-lifecycle.lock"
    lifecycle_owner_path = tmp_path / "installer-lifecycle.owner"
    behavior_script.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{literal(PACKAGING / "windows_release_config.ps1")}'
. '{literal(PACKAGING / "windows_service_lifecycle.ps1")}'
. '{literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{literal(PACKAGING / "windows_lifecycle_lock.ps1")}'
. '{literal(PACKAGING / "windows_bundled_database.ps1")}'
Assert-TicketboxPowerShellBitness -Is64BitOperatingSystem $true -Is64BitProcess $true
$bitnessRejected = $false
try {{
    Assert-TicketboxPowerShellBitness -Is64BitOperatingSystem $true -Is64BitProcess $false
}}
catch {{
    if ($_.Exception.Message -notlike '*64 位 PowerShell*') {{ throw }}
    $bitnessRejected = $true
}}
if (-not $bitnessRejected) {{ throw '32-bit PowerShell host was accepted' }}
$trustedSc = Get-TicketboxTrustedScExecutable
$expectedSc = [System.IO.Path]::GetFullPath((Join-Path ([Environment]::SystemDirectory) 'sc.exe'))
if (-not [System.IO.Path]::IsPathRooted($trustedSc) -or
    -not [string]::Equals($trustedSc, $expectedSc, [System.StringComparison]::OrdinalIgnoreCase)) {{
    throw 'trusted sc.exe did not resolve from the Windows system directory'
}}
$trustedScItem = Get-Item -LiteralPath $trustedSc -Force -ErrorAction Stop
if (($trustedScItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {{
    throw 'trusted sc.exe resolved to a reparse point'
}}
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$ownerIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
Write-TicketboxLifecycleLockOwnerRecord `
    -Path '{literal(lifecycle_owner_path)}' `
    -OwnerIdentity $ownerIdentity `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$lifecycleHandle = [System.IO.File]::Open(
    '{literal(lifecycle_lock_path)}',
    [System.IO.FileMode]::OpenOrCreate,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::None
)
function Get-TicketboxLifecycleLockPath {{ return '{literal(lifecycle_lock_path)}' }}
function Get-TicketboxLifecycleLockOwnerPath {{ return '{literal(lifecycle_owner_path)}' }}
function Get-TicketboxParentProcessId {{ return $PID }}
try {{
    Assert-TicketboxExternalLifecycleLock `
        -OwnerProcessId $PID `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
finally {{
    $lifecycleHandle.Dispose()
}}
$releasedLockRejected = $false
try {{
    Assert-TicketboxExternalLifecycleLock `
        -OwnerProcessId $PID `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
catch {{ $releasedLockRejected = $true }}
if (-not $releasedLockRejected) {{ throw 'released external lifecycle lock was accepted' }}
$script:deadlineProbeCount = 0
$timedOut = $false
try {{
    Wait-TicketboxServiceSettledState -Name Demo -TimeoutMilliseconds 20 -PollMilliseconds 20 -StateReader {{ param($Name) $script:deadlineProbeCount += 1; 'startpending' }} -SleepAction {{ param($Ms) Start-Sleep -Milliseconds ($Ms + 25) }} | Out-Null
}} catch {{ $timedOut = $true }}
if (-not $timedOut -or $script:deadlineProbeCount -ne 1) {{ throw 'deadline allowed a post-timeout probe' }}
$script:runtimePoll = 0
Wait-TicketboxBackendRuntimeStopped `
    -Name DemoBackend `
    -BackendPort 8765 `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\ticketbox-backend.exe', 'C:\\Ticketbox\\shawl.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1 `
    -ListenerReader {{
        param($Port)
        $script:runtimePoll += 1
        return @()
    }} `
    -RuntimeProcessReader {{
        if ($script:runtimePoll -eq 1) {{
            return [pscustomobject]@{{
                Name = 'ticketbox-backend.exe'
            ExecutablePath = 'C:\\Ticketbox\\ticketbox-backend.exe'
                ProcessId = 5101
            }}
        }}
        return @()
    }} `
    -SleepAction {{ param($Ms) }}
if ($script:runtimePoll -ne 2) {{ throw 'backend runtime stop proof ignored a drift-port orphan process' }}
$script:pidReusePoll = 0
Wait-TicketboxBackendRuntimeStopped `
    -Name DemoBackend `
    -BackendPort 8765 `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\ticketbox-backend.exe', 'C:\\Ticketbox\\shawl.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1 `
    -ListenerReader {{ param($Port) return @() }} `
    -RuntimeProcessReader {{
        $script:pidReusePoll += 1
        return [pscustomobject]@{{
            Name = 'unrelated.exe'
            ExecutablePath = 'C:\\Other\\unrelated.exe'
            ProcessId = 4101
        }}
    }} `
    -SleepAction {{ param($Ms) }}
if ($script:pidReusePoll -ne 1) {{ throw 'unrelated reused PID blocked runtime stop proof' }}
$script:zeroPortRuntimePoll = 0
Wait-TicketboxBackendRuntimeStopped `
    -Name DemoPg `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\postgres.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1 `
    -RuntimeProcessReader {{
        $script:zeroPortRuntimePoll += 1
        if ($script:zeroPortRuntimePoll -eq 1) {{
            return [pscustomobject]@{{
                Name = 'postgres.exe'
                ExecutablePath = 'C:\\Ticketbox\\postgres.exe'
                ProcessId = 5201
            }}
        }}
        return @()
    }} `
    -SleepAction {{ param($Ms) }}
if ($script:zeroPortRuntimePoll -ne 2) {{
    throw 'BackendPort=0 bypassed the expected-runtime executable scan'
}}
$script:missingServiceRuntimeChecks = 0
function Assert-TicketboxServiceOwnership([string]$Name, [string]$ExpectedExecutable) {{ return $false }}
function Get-TicketboxExpectedRuntimeProcessIds {{
    param([string[]]$ExpectedExecutables, [scriptblock]$ProcessSnapshotReader)
    $script:missingServiceRuntimeChecks += 1
    return @()
}}
Stop-TicketboxOwnedServiceIfExists `
    -Name MissingBackend `
    -ExpectedExecutable 'C:\\Ticketbox\\shawl.exe' `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\ticketbox-backend.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1
Remove-TicketboxOwnedServiceIfExists `
    -Name MissingPg `
    -ExpectedExecutable 'C:\\Ticketbox\\pg_ctl.exe' `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\postgres.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1
if ($script:missingServiceRuntimeChecks -ne 2) {{
    throw 'missing SCM records bypassed runtime executable scans'
}}
$script:zeroPortStopWaits = 0
function Assert-TicketboxServiceOwnership([string]$Name, [string]$ExpectedExecutable) {{ return $true }}
function Get-TicketboxServiceProcessId([string]$Name) {{ return 6101 }}
function Wait-TicketboxServiceSettledState {{
    param([string]$Name, [int]$TimeoutMilliseconds, [int]$PollMilliseconds)
    return 'stopped'
}}
function Wait-TicketboxBackendRuntimeStopped {{
    param(
        [string]$Name,
        [int]$BackendPort,
        [string[]]$ExpectedRuntimeExecutables,
        [int]$TimeoutMilliseconds,
        [int]$PollMilliseconds
    )
    $script:zeroPortStopWaits += 1
    if ($BackendPort -ne 0) {{ throw 'PostgreSQL stop unexpectedly required a backend port' }}
    if ($ExpectedRuntimeExecutables.Count -ne 1 -or
        $ExpectedRuntimeExecutables[0] -cne 'C:\\Ticketbox\\postgres.exe') {{
        throw 'BackendPort=0 did not forward expected runtime executables'
    }}
}}
Stop-TicketboxOwnedServiceIfExists `
    -Name DemoPg `
    -ExpectedExecutable 'C:\\Ticketbox\\pg_ctl.exe' `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\postgres.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1
if ($script:zeroPortStopWaits -ne 1) {{
    throw 'BackendPort=0 skipped the post-stop runtime proof'
}}
Set-Content -LiteralPath '{literal(secret_path)}' -Value 'secret'
$handle = [System.IO.File]::Open('{literal(secret_path)}', 'Open', 'Read', 'None')
$blocked = $false
try {{ Remove-TicketboxSensitiveFile '{literal(secret_path)}' }} catch {{ $blocked = $true }}
finally {{ $handle.Dispose() }}
if (-not $blocked) {{ throw 'locked sensitive file deletion failed open' }}
Remove-TicketboxSensitiveFile '{literal(secret_path)}'
if (Test-Path -LiteralPath '{literal(secret_path)}') {{ throw 'sensitive file survived verified cleanup' }}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", behavior_script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
