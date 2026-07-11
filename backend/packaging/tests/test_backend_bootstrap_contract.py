from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = PACKAGING / "windows_backend_bootstrap.ps1"


def _read() -> str:
    return BOOTSTRAP_SCRIPT.read_text(encoding="utf-8-sig")


def test_bootstrap_checks_listener_chain_and_durable_credentials() -> None:
    script = _read()
    recovery = (PACKAGING / "windows_bootstrap_exposure_recovery.ps1").read_text(
        encoding="utf-8-sig"
    )
    install = (PACKAGING / "install_bundled_services.ps1").read_text(encoding="utf-8-sig")

    assert "Get-NetTCPConnection" in script
    assert '-LocalAddress "127.0.0.1"' in script
    assert "Win32_Service" in script
    assert "Win32_Process" in script
    assert "listener.ParentProcessId" in script
    assert "Assert-TicketboxBackendListenerUnchanged" in script
    assert "Invoke-TicketboxOwnerBootstrapHttpRequest" in script
    assert "bootstrap secret 可能已暴露" in script
    assert "catch [System.Security.SecurityException]" in script
    assert '"http://127.0.0.1:$BackendPort/api/health/installation"' in script
    assert '@($Payload.PSObject.Properties).Count -ne 4' in script
    assert '[string]$Payload.status -cne "ok"' in script
    assert '[string]$Payload.product -cne "ticketbox"' in script
    assert "Get-TicketboxExpectedBackendVersion" in script
    assert "Get-TicketboxExpectedInstallationId" in script
    assert '[string]$Payload.backend_version -cne $ExpectedBackendVersion' in script
    assert '[string]$Payload.installation_id -cne $ExpectedInstallationId' in script
    assert '"ticketbox-installation-v1`0$canonicalDataRoot"' in script
    assert '[System.Text.Encoding]::UTF8.GetBytes($bodyText)' in script
    assert '$request.ContentType = "application/json; charset=utf-8"' in script
    assert "$request.Proxy = $null" in script
    assert "$request.AllowAutoRedirect = $false" in script
    assert "Read-TicketboxBoundedUtf8HttpResponse" in script
    assert "$script:BootstrapMaximumResponseBytes" in script
    assert "Invoke-RestMethod" not in script
    assert "Invoke-WebRequest" not in script
    assert "Assert-TicketboxBootstrapResponse" in script
    assert "Set-TicketboxExactFileAcl" in script
    assert "Write-TicketboxOwnerHandoffPendingMarker" in script
    assert "Complete-TicketboxOwnerBootstrapHandoff" in script
    handoff_cleanup = script[script.index("function Complete-TicketboxOwnerBootstrapHandoff") :]
    read_state = handoff_cleanup.index("Read-TicketboxOwnerHandoffState")
    confirm = handoff_cleanup.index("Set-TicketboxOwnerHandoffConfirmed")
    remove_credential = handoff_cleanup.index("Remove-TicketboxSensitiveFile $OwnerBootstrapPath")
    remove_marker = handoff_cleanup.index("Remove-TicketboxSensitiveFile $OwnerHandoffPendingPath")
    assert read_state < confirm < remove_credential < remove_marker
    assert 'if (Test-Path -LiteralPath $OwnerBootstrapPath)' in handoff_cleanup
    assert "STATE=confirmed" in script
    assert "INSTALLER_OWNER_PID=" in script
    assert script.index("Write-TicketboxOwnerHandoffPendingMarker") < script.index(
        "Write-EnvNoBom -Path $OwnerBootstrapPath"
    )
    assert script.index("Write-TicketboxOwnerBootstrapFile $response") < script.index(
        "Write-EnvNoBom -Path $EnvPath"
    )
    assert "bootstrap_already_initialized" not in script
    assert "Write-TicketboxBootstrapExposureRecoveryIntent" in recovery
    assert "Write-TicketboxBootstrapQuarantineEnvironment" in recovery
    assert "Resolve-TicketboxBootstrapExposureRecoveryIntent" in recovery
    assert "Protect-TicketboxBootstrapAfterRepeatedListenerFailure" in script
    repeated_failure = recovery[
        recovery.index("function Protect-TicketboxBootstrapAfterRepeatedListenerFailure") :
        recovery.index("function Resolve-TicketboxBootstrapExposureRecoveryIntent")
    ]
    guard = repeated_failure.index("Write-TicketboxBootstrapExposureRecoveryGuard")
    intent = repeated_failure.index("Write-TicketboxBootstrapExposureRecoveryIntent")
    quarantine = repeated_failure.index("Write-TicketboxBootstrapQuarantineEnvironment")
    disable = repeated_failure.index("Disable-TicketboxOwnedServiceIfExists")
    stopped = repeated_failure.index("Wait-TicketboxBackendRuntimeStopped")
    assert guard < intent < quarantine < disable < stopped
    second_failure = script[script.index("if ($listenerExposureRecovered)") :]
    assert second_failure.index("Protect-TicketboxBootstrapAfterRepeatedListenerFailure") < second_failure.index(
        "replacement listener 后验复核再次失败"
    )
    recovery_entry = recovery[recovery.index("function Invoke-TicketboxBootstrapExposureRecovery") :]
    assert recovery_entry.index("Write-TicketboxBootstrapExposureRecoveryGuard") < recovery_entry.index(
        "Write-TicketboxBootstrapExposureRecoveryIntent"
    )
    assert recovery_entry.index("Write-TicketboxBootstrapExposureRecoveryIntent") < recovery_entry.index(
        "Disable-TicketboxOwnedServiceIfExists"
    )
    resolve_entry = recovery[recovery.index("function Resolve-TicketboxBootstrapExposureRecoveryIntent") :]
    assert resolve_entry.index("Disable-TicketboxOwnedServiceIfExists") < resolve_entry.index(
        "Write-TicketboxBootstrapQuarantineEnvironment"
    )
    assert "Write-TicketboxBootstrapEnabledEnvironment $DatabaseUrl $ExposedSecret" not in recovery
    assert install.index("Resolve-TicketboxBootstrapExposureRecoveryIntent") < install.index(
        'Write-Step "启动后端服务"'
    )


def test_maintenance_failure_writes_credential_free_durable_result(tmp_path: Path) -> None:
    exposed_secret = "exposed-bootstrap-secret-for-diagnostic-test"
    replacement_secret = "replacement-bootstrap-secret-for-diagnostic-test"
    operation_id = str(uuid.uuid4())
    data_dir = tmp_path / "app-data"
    env = os.environ.copy()
    env.update(
        {
            "TICKETBOX_DATA_DIR": str(data_dir),
            "TICKETBOX_MAINTENANCE_ACTION": "rotate-exposed-bootstrap",
            "TICKETBOX_MAINTENANCE_OPERATION_ID": operation_id,
            "TICKETBOX_EXPOSED_BOOTSTRAP_SECRET": exposed_secret,
            "TICKETBOX_REPLACEMENT_BOOTSTRAP_SECRET": replacement_secret,
            "DATABASE_URL": (
                "postgresql+psycopg://postgres@127.0.0.1:1/xpj_test?connect_timeout=1"
            ),
            "PYTHONPATH": str(PACKAGING.parent),
        }
    )
    result = subprocess.run(
        [sys.executable, str(PACKAGING / "launch.py")],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=20,
    )
    assert result.returncode != 0
    result_path = data_dir / "logs" / "bootstrap-exposure-recovery-result.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema": "ticketbox-maintenance-result-v1",
        "action": "rotate-exposed-bootstrap",
        "operation_id": operation_id,
        "state": "failed",
        "error_code": "database_error",
        "error_type": "OperationalError",
        "recorded_at_utc": payload["recorded_at_utc"],
    }
    log_text = (data_dir / "logs" / "backend.log").read_text(encoding="utf-8")
    evidence = result.stdout + result.stderr + log_text + result_path.read_text(encoding="utf-8")
    assert exposed_secret not in evidence
    assert replacement_secret not in evidence
    assert "database_error" in log_text


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell recovery intent contract")
def test_exposure_recovery_intent_survives_quiescence_failure_and_resumes(
    tmp_path: Path,
) -> None:
    recovery_script = str(PACKAGING / "windows_bootstrap_exposure_recovery.ps1").replace("'", "''")
    intent_path = str(tmp_path / "recovery.env").replace("'", "''")
    env_path = str(tmp_path / ".env").replace("'", "''")
    harness = tmp_path / "bootstrap-exposure-intent.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{recovery_script}'
$BootstrapExposureRecoveryPath = '{intent_path}'
$BootstrapExposureRecoveryGuardPath = '{str(tmp_path / "recovery.pending").replace("'", "''")}'
$EnvPath = '{env_path}'
$AppData = '{str(tmp_path).replace("'", "''")}'
$BackendServiceName = 'TicketboxBackend'
$ShawlExe = 'C:\\Ticketbox\\shawl.exe'
$BackendExe = 'C:\\Ticketbox\\ticketbox-backend.exe'
$BackendPort = 8123
$ServiceWaitArguments = @{{ TimeoutMilliseconds = 1000; PollMilliseconds = 1 }}
$script:disableFails = $true
$script:disableCalls = 0
$script:quiescenceProofs = 0
$script:maintenanceCalls = 0
$script:newSecretCalls = 0
$script:collisionOnce = $false
function Write-EnvNoBom([string]$Path, [string[]]$Lines) {{
        [System.IO.File]::WriteAllText(
            $Path,
            (($Lines -join [Environment]::NewLine) + [Environment]::NewLine),
        (New-Object System.Text.UTF8Encoding($false))
    )
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    $temporary = "$Path.tmp"
    [System.IO.File]::WriteAllText($temporary, $Text, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $Path
}}
function Move-TicketboxFileDurable {{
    param($Source, $Destination, [switch]$ReplaceExisting)
    Move-Item -LiteralPath $Source -Destination $Destination -Force:$ReplaceExisting
}}
function Read-EnvMap([string]$Path) {{
    $map = @{{}}
        foreach ($line in [System.IO.File]::ReadAllLines($Path)) {{
            if ($line.Length -eq 0) {{ continue }}
            $separator = $line.IndexOf('=')
            if ($separator -le 0) {{ throw 'invalid environment line' }}
            $map[$line.Substring(0, $separator)] = $line.Substring($separator + 1)
    }}
    return $map
}}
function New-BaseEnvLines([string]$DatabaseUrl) {{
    return @("DATABASE_URL=$DatabaseUrl", 'TICKETBOX_HOST=127.0.0.1')
}}
function New-HttpBootstrapSecret {{
    $script:newSecretCalls += 1
    if ($script:newSecretCalls -eq 1) {{ return 'replacement-secret-with-at-least-32-bytes' }}
    if ($script:newSecretCalls -eq 2) {{ return 'second-replacement-secret-with-at-least-32-bytes' }}
    if ($script:newSecretCalls -eq 3) {{ return 'colliding-replacement-secret-with-32-bytes' }}
    return 'collision-retry-secret-with-at-least-32-bytes'
}}
function Get-TicketboxBootstrapCredentials([string]$Secret) {{ return [pscustomobject]@{{ Secret = $Secret }} }}
function Set-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function Assert-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function Remove-TicketboxSensitiveFile([string]$Path) {{ Remove-Item -LiteralPath $Path -Force }}
function Disable-TicketboxOwnedServiceIfExists {{
    $script:disableCalls += 1
    if ($script:disableFails) {{ throw 'simulated quiescence failure' }}
}}
function Wait-TicketboxBackendRuntimeStopped {{ $script:quiescenceProofs += 1 }}
function Invoke-TicketboxBootstrapExposureMaintenance([string]$ExposedSecret, [string]$ReplacementSecret) {{
    $firstGeneration = (
        $ExposedSecret -ceq 'exposed-secret-with-at-least-32-bytes' -and
        $ReplacementSecret -ceq 'replacement-secret-with-at-least-32-bytes'
    )
    $secondGeneration = (
        $ExposedSecret -ceq 'replacement-secret-with-at-least-32-bytes' -and
        $ReplacementSecret -ceq 'second-replacement-secret-with-at-least-32-bytes'
    )
    $collisionGeneration = (
        $ExposedSecret -ceq 'second-replacement-secret-with-at-least-32-bytes' -and
        $ReplacementSecret -ceq 'colliding-replacement-secret-with-32-bytes'
    )
    $collisionRetryGeneration = (
        $ExposedSecret -ceq 'second-replacement-secret-with-at-least-32-bytes' -and
        $ReplacementSecret -ceq 'collision-retry-secret-with-at-least-32-bytes'
    )
    if (-not ($firstGeneration -or $secondGeneration -or $collisionGeneration -or $collisionRetryGeneration)) {{
        throw 'wrong recovery generation'
    }}
    $script:maintenanceCalls += 1
    if ($collisionGeneration -and $script:collisionOnce) {{
        $script:collisionOnce = $false
        return [pscustomobject]@{{ state = 'failed'; error_code = 'replacement_credential_collision' }}
    }}
    return [pscustomobject]@{{ state = 'succeeded'; error_code = '' }}
}}
function Set-TicketboxOwnedServiceStartPolicyIfExists {{ param($Name, $ExpectedExecutable, $StartPolicy) }}
function Start-TicketboxOwnedServiceIfExists {{ param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds) }}
function Wait-BackendHealth {{ }}
Write-TicketboxBootstrapEnabledEnvironment `
    'postgresql://local/test' `
    'exposed-secret-with-at-least-32-bytes'
$failed = $false
try {{
    Invoke-TicketboxBootstrapExposureRecovery `
        'postgresql://local/test' `
        'exposed-secret-with-at-least-32-bytes' | Out-Null
}}
catch {{ $failed = $true }}
if (-not $failed) {{ throw 'quiescence failure did not abort recovery' }}
if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryPath)) {{ throw 'recovery intent was lost' }}
if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath)) {{ throw 'startup guard was lost' }}
$guardedEnvironment = Read-EnvMap $EnvPath
if ($guardedEnvironment['HTTP_BOOTSTRAP_SECRET'] -cne 'exposed-secret-with-at-least-32-bytes') {{
    throw 'pre-quiescence environment changed unexpectedly'
}}
$script:disableFails = $false
$replacement = Resolve-TicketboxBootstrapExposureRecoveryIntent `
    -DatabaseUrl 'postgresql://local/test' `
    -StartBackendAfterRecovery $false
if ($replacement -cne 'replacement-secret-with-at-least-32-bytes') {{ throw 'resume returned wrong secret' }}
if ($script:maintenanceCalls -ne 1) {{ throw 'maintenance action count mismatch' }}
if (Test-Path -LiteralPath $BootstrapExposureRecoveryPath) {{ throw 'resolved intent survived cleanup' }}
if (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath) {{ throw 'resolved startup guard survived cleanup' }}
$enabled = Read-EnvMap $EnvPath
if ($enabled['HTTP_BOOTSTRAP_SECRET'] -cne $replacement) {{ throw 'replacement secret was not enabled' }}
$script:disableFails = $true
$repeatFailed = $false
try {{
    Protect-TicketboxBootstrapAfterRepeatedListenerFailure `
        -DatabaseUrl 'postgresql://local/test' `
        -ExposedSecret $replacement
}}
catch {{ $repeatFailed = $true }}
if (-not $repeatFailed) {{ throw 'second listener failure ignored quiescence failure' }}
if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryPath)) {{ throw 'failed quarantine lost recovery intent' }}
if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath)) {{ throw 'failed quarantine lost startup guard' }}
$stillEnabled = Read-EnvMap $EnvPath
if ($stillEnabled.ContainsKey('ENABLE_HTTP_BOOTSTRAP') -or $stillEnabled.ContainsKey('HTTP_BOOTSTRAP_SECRET')) {{
    throw 'failed quarantine left exposed runtime configuration enabled'
}}
$script:disableFails = $false
$secondReplacement = Resolve-TicketboxBootstrapExposureRecoveryIntent `
    -DatabaseUrl 'postgresql://local/test' `
    -StartBackendAfterRecovery $false
if ($secondReplacement -cne 'second-replacement-secret-with-at-least-32-bytes') {{ throw 'second repair returned wrong secret' }}
if (Test-Path -LiteralPath $BootstrapExposureRecoveryPath) {{ throw 'second resolved intent survived cleanup' }}
if (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath) {{ throw 'second resolved guard survived cleanup' }}
$quarantined = Read-EnvMap $EnvPath
if ($quarantined['HTTP_BOOTSTRAP_SECRET'] -cne $secondReplacement) {{
    throw 'second replacement secret was not enabled after repair'
}}
if ($script:maintenanceCalls -ne 2) {{ throw 'second repair maintenance count mismatch' }}
if ($script:disableCalls -ne 4) {{ throw 'owned backend was not disabled for every recovery attempt' }}
if ($script:quiescenceProofs -ne 0) {{ throw 'failed repeated listener stop unexpectedly reached quiescence proof' }}
$script:collisionOnce = $true
$collisionRetry = Invoke-TicketboxBootstrapExposureRecovery `
    -DatabaseUrl 'postgresql://local/test' `
    -ExposedSecret $secondReplacement `
    -StartBackendAfterRecovery $false
if ($collisionRetry -cne 'collision-retry-secret-with-at-least-32-bytes') {{
    throw 'credential collision did not rotate the persisted replacement generation'
}}
if ($script:maintenanceCalls -ne 4) {{ throw 'credential collision retry count mismatch' }}
if ($script:disableCalls -ne 5) {{ throw 'credential collision recovery did not quiesce backend once' }}
if (Test-Path -LiteralPath $BootstrapExposureRecoveryPath) {{ throw 'collision retry intent survived cleanup' }}
if (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath) {{ throw 'collision retry guard survived cleanup' }}
$collisionEnabled = Read-EnvMap $EnvPath
if ($collisionEnabled['HTTP_BOOTSTRAP_SECRET'] -cne $collisionRetry) {{
    throw 'collision retry replacement was not enabled'
}}
""",
        encoding="utf-8-sig",
    )
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    for engine in engines:
        (tmp_path / "recovery.env").unlink(missing_ok=True)
        (tmp_path / "recovery.pending").unlink(missing_ok=True)
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
        assert "exposed-secret-with-at-least-32-bytes" not in result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell owner handoff cleanup contract")
def test_owner_handoff_cleanup_is_confirmed_before_crash_idempotent_deletion(tmp_path: Path) -> None:
    harness = tmp_path / "owner-handoff-cleanup.ps1"
    bootstrap_script = str(BOOTSTRAP_SCRIPT).replace("'", "''")
    owner_path = str(tmp_path / "owner-bootstrap.txt").replace("'", "''")
    pending_path = str(tmp_path / "owner-handoff-pending").replace("'", "''")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{bootstrap_script}'
$OwnerBootstrapPath = '{owner_path}'
$OwnerHandoffPendingPath = '{pending_path}'
$InstallDir = '{str(tmp_path / "install").replace("'", "''")}'
$DataRoot = '{str(tmp_path / "data").replace("'", "''")}'
$InstallerLockOwnerProcessId = $PID
$script:rejectMarkerAcl = $true
$script:crashBeforeMarkerDeletion = $false
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{ }}
function ConvertTo-TicketboxCanonicalPath([string]$Path) {{ return [IO.Path]::GetFullPath($Path) }}
function Assert-TicketboxExactFileAcl {{
    param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount)
    if ($script:rejectMarkerAcl -and $Path -ceq $OwnerHandoffPendingPath) {{
        throw 'simulated marker ACL substitution'
    }}
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    $temporary = "$Path.tmp"
    [System.IO.File]::WriteAllText($temporary, $Text, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}}
function Remove-TicketboxSensitiveFile([string]$Path) {{
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{ throw 'not a leaf' }}
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {{ throw 'reparse point' }}
    if ($script:crashBeforeMarkerDeletion -and $Path -ceq $OwnerHandoffPendingPath) {{
        $script:crashBeforeMarkerDeletion = $false
        throw 'simulated crash before marker deletion'
    }}
    Remove-Item -LiteralPath $Path -Force
    if (Test-Path -LiteralPath $Path) {{ throw 'deletion not durable' }}
}}
[System.IO.File]::WriteAllText($OwnerBootstrapPath, 'credential')
$credentialHash = Get-TicketboxOwnerHandoffTextSha256 'credential'
Write-TicketboxOwnerHandoffMarker `
    -State 'pending' `
    -Generation ([Guid]::NewGuid().ToString('D')) `
    -CredentialSha256 $credentialHash
if (-not (Test-Path $OwnerBootstrapPath) -or -not (Test-Path $OwnerHandoffPendingPath)) {{
    throw 'pending handoff did not retain both files'
}}
$blocked = $false
try {{ Complete-TicketboxOwnerBootstrapHandoff }} catch {{ $blocked = $true }}
if (-not $blocked) {{ throw 'invalid marker ACL did not block cleanup' }}
if (-not (Test-Path $OwnerBootstrapPath) -or -not (Test-Path $OwnerHandoffPendingPath)) {{
    throw 'partial cleanup occurred before both artifacts were validated'
}}
$script:rejectMarkerAcl = $false
$script:crashBeforeMarkerDeletion = $true
$crashed = $false
try {{ Complete-TicketboxOwnerBootstrapHandoff }} catch {{ $crashed = $true }}
if (-not $crashed) {{ throw 'simulated crash was not observed' }}
if (Test-Path $OwnerBootstrapPath) {{ throw 'credential survived confirmed cleanup phase' }}
$confirmed = Read-TicketboxOwnerHandoffRecord
if ($confirmed.State -cne 'confirmed' -or $confirmed.OwnerProcessId -ne $PID) {{
    throw 'confirmed state was not durable before credential deletion'
}}
Complete-TicketboxOwnerBootstrapHandoff
if ((Test-Path $OwnerBootstrapPath) -or (Test-Path $OwnerHandoffPendingPath)) {{
    throw 'confirmed handoff artifacts survived cleanup'
}}
""",
        encoding="utf-8-sig",
    )
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
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


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell owner handoff takeover contract")
def test_owner_handoff_takeover_requires_dead_previous_installer(tmp_path: Path) -> None:
    harness = tmp_path / "owner-handoff-takeover.ps1"
    bootstrap_script = str(BOOTSTRAP_SCRIPT).replace("'", "''")
    owner_path = str(tmp_path / "owner-bootstrap.txt").replace("'", "''")
    pending_path = str(tmp_path / "owner-handoff-pending").replace("'", "''")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{bootstrap_script}'
$OwnerBootstrapPath = '{owner_path}'
$OwnerHandoffPendingPath = '{pending_path}'
$InstallDir = '{str(tmp_path / "install").replace("'", "''")}'
$DataRoot = '{str(tmp_path / "data").replace("'", "''")}'
$EnvPath = '{str(tmp_path / ".env").replace("'", "''")}'
$currentInstallerPid = $PID
$InstallerLockOwnerProcessId = $currentInstallerPid
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{ }}
function Assert-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function ConvertTo-TicketboxCanonicalPath([string]$Path) {{ return [IO.Path]::GetFullPath($Path) }}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}}
function Remove-TicketboxSensitiveFile([string]$Path) {{
    Remove-Item -LiteralPath $Path -Force
}}
function Read-EnvMap([string]$Path) {{ return @{{}} }}
function New-OldOwnerProcess {{
    $executable = (Get-Process -Id $PID).Path
    return Start-Process `
        -FilePath $executable `
        -ArgumentList @('-NoLogo', '-NoProfile', '-Command', 'Start-Sleep -Seconds 30') `
        -WindowStyle Hidden `
        -PassThru
}}
function Write-OldOwnerHandoff([object]$OldOwner, [string]$State, [bool]$IncludeCredential) {{
    $credential = 'credential-for-takeover'
    $hash = Get-TicketboxOwnerHandoffTextSha256 $credential
    if ($IncludeCredential) {{
        [System.IO.File]::WriteAllText($OwnerBootstrapPath, $credential)
    }}
    $script:InstallerLockOwnerProcessId = $OldOwner.Id
    Write-TicketboxOwnerHandoffMarker `
        -State $State `
        -Generation ([Guid]::NewGuid().ToString('D')) `
        -CredentialSha256 $hash
    $script:InstallerLockOwnerProcessId = $currentInstallerPid
}}

$liveOwner = New-OldOwnerProcess
try {{
    Write-OldOwnerHandoff $liveOwner 'pending' $true
    $blocked = $false
    try {{ Adopt-TicketboxOwnerBootstrapHandoff | Out-Null }} catch {{ $blocked = $true }}
    if (-not $blocked) {{ throw 'live previous installer was adopted' }}
    $stillOld = Read-TicketboxOwnerHandoffRecord
    if ($stillOld.OwnerProcessId -ne $liveOwner.Id) {{ throw 'live-owner marker was rewritten' }}
}}
finally {{
    Stop-Process -Id $liveOwner.Id -Force -ErrorAction SilentlyContinue
    $liveOwner.WaitForExit()
}}
$adopted = Adopt-TicketboxOwnerBootstrapHandoff
if ($adopted -cne 'pending') {{ throw 'dead previous installer was not adopted' }}
$current = Read-TicketboxOwnerHandoffRecord
if ($current.OwnerProcessId -ne $currentInstallerPid) {{ throw 'adopted marker owner mismatch' }}
Complete-TicketboxOwnerBootstrapHandoff

$confirmedOwner = New-OldOwnerProcess
try {{
    Write-OldOwnerHandoff $confirmedOwner 'confirmed' $true
    Remove-Item -LiteralPath $OwnerBootstrapPath -Force
}}
finally {{
    Stop-Process -Id $confirmedOwner.Id -Force -ErrorAction SilentlyContinue
    $confirmedOwner.WaitForExit()
}}
$cleaned = Adopt-TicketboxOwnerBootstrapHandoff
if ($cleaned -cne 'cleaned_confirmed') {{ throw 'confirmed handoff was redisplayed' }}
if ((Test-Path $OwnerBootstrapPath) -or (Test-Path $OwnerHandoffPendingPath)) {{
    throw 'confirmed handoff cleanup left artifacts'
}}
""",
        encoding="utf-8-sig",
    )
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell cross-runtime contract")
def test_bootstrap_hmac_vector_matches_backend_in_powershell_5_and_7(tmp_path: Path) -> None:
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    harness = tmp_path / "bootstrap-vector.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(BOOTSTRAP_SCRIPT).replace("'", "''")}'
$value = Get-TicketboxBootstrapCredentials 'ticketbox-bootstrap-vector-2026-07-10'
if ($value.AdminToken -cne 'tbx_f1cz5I0IKi0r6iUzmoexescoDH0xYOF7_-R39LpN7lY') {{
    throw 'admin token vector mismatch'
}}
if ($value.UploadKey -cne 'upl_I8Q7_d0BrxgzKxMlkZFUtd9eFF1xe40zM8dt2h1cyeU') {{
    throw 'upload key vector mismatch'
}}
if ($value.PairingCode -cne '05747978') {{ throw 'pairing vector mismatch' }}
$rejected = $false
try {{ Get-TicketboxBootstrapCredentials 'human-password' | Out-Null }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'weak bootstrap secret accepted' }}
""",
        encoding="utf-8-sig",
    )
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


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell direct loopback contract")
def test_bootstrap_request_bypasses_default_proxy(tmp_path: Path) -> None:
    app_data = (tmp_path / "data" / "app").resolve()
    expected_installation_id = "ticketbox-" + hashlib.sha256(
        b"ticketbox-installation-v1\0" + os.path.normcase(str(app_data)).encode()
    ).hexdigest()[:32]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        health_calls = 0

        def do_GET(self) -> None:  # noqa: N802
            assert self.path == "/api/health/installation"
            self.__class__.health_calls += 1
            position = ((self.__class__.health_calls - 1) % 3) + 1
            if position == 1:
                body = json.dumps(
                    {
                        "status": "ok",
                        "product": "ticketbox",
                        "backend_version": "7.8.9",
                        "installation_id": expected_installation_id,
                    },
                    separators=(",", ":"),
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if position == 2:
                self.send_response(302)
                self.send_header("Location", "/api/health/installation")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b"x" * 65536
            try:
                for _ in range(17):
                    self.wfile.write(f"{len(chunk):X}\r\n".encode())
                    self.wfile.write(chunk + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:  # noqa: N802
            assert self.path == "/api/bootstrap/owner"
            assert self.headers["X-Bootstrap-Secret"] == "proxy-bypass-test-secret-with-32-byte-minimum"
            content_length = int(self.headers["Content-Length"])
            assert self.rfile.read(content_length) == b"{}"
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Handler.health_calls = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
        assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
        harness = tmp_path / "bootstrap-proxy-bypass.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{str(BOOTSTRAP_SCRIPT).replace("'", "''")}'
$AppData = '{str(app_data).replace("'", "''")}'
$ProgramDir = '{str(tmp_path).replace("'", "''")}'
function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}}
Set-Content `
    -LiteralPath (Join-Path $ProgramDir 'BUILD_PROVENANCE.json') `
    -Encoding UTF8 `
    -Value '{{"backend_version":"7.8.9"}}'
Add-Type -TypeDefinition @'
using System;
using System.Net;
using System.Threading;
public sealed class TicketboxThrowingProxy : IWebProxy
{{
    public static int Calls;
    public ICredentials Credentials {{ get; set; }}
    public Uri GetProxy(Uri destination)
    {{
        Interlocked.Increment(ref Calls);
        throw new InvalidOperationException("default proxy was consulted");
    }}
    public bool IsBypassed(Uri host)
    {{
        Interlocked.Increment(ref Calls);
        throw new InvalidOperationException("default proxy was consulted");
    }}
}}
'@
$script:listenerChecks = 0
function Get-TicketboxBackendListenerIdentity {{ return [pscustomobject]@{{ Id = 1 }} }}
function Assert-TicketboxBackendListenerUnchanged([object]$ExpectedIdentity) {{
    $script:listenerChecks += 1
}}
$previousProxy = [System.Net.WebRequest]::DefaultWebProxy
try {{
    [TicketboxThrowingProxy]::Calls = 0
    [System.Net.WebRequest]::DefaultWebProxy = New-Object TicketboxThrowingProxy
    $body = [System.Text.Encoding]::UTF8.GetBytes('{{}}')
    $response = Invoke-TicketboxOwnerBootstrapHttpRequest `
        -Url 'http://127.0.0.1:{server.server_port}/api/bootstrap/owner' `
        -Secret 'proxy-bypass-test-secret-with-32-byte-minimum' `
        -BodyBytes $body `
        -TimeoutMilliseconds 5000
    if (-not $response.ok) {{ throw 'loopback JSON response was not parsed' }}
    $health = Invoke-TicketboxDirectLoopbackHealthHttpRequest `
        -Url 'http://127.0.0.1:{server.server_port}/api/health/installation' `
        -TimeoutMilliseconds 5000
    $expectedVersion = Get-TicketboxExpectedBackendVersion
    $expectedInstallationId = Get-TicketboxExpectedInstallationId
    Assert-TicketboxInstallationHealthResponse `
        -Payload $health `
        -ExpectedBackendVersion $expectedVersion `
        -ExpectedInstallationId $expectedInstallationId
    if ($expectedVersion -cne '7.8.9') {{ throw 'backend version was not read dynamically' }}
    if ($expectedInstallationId -cne '{expected_installation_id}') {{
        throw 'installation id did not match the backend data-root contract'
    }}
    foreach ($field in @('status', 'product', 'backend_version', 'installation_id')) {{
        $invalid = $health.PSObject.Copy()
        $invalid.$field = 'wrong'
        $rejected = $false
        try {{
            Assert-TicketboxInstallationHealthResponse `
                -Payload $invalid `
                -ExpectedBackendVersion $expectedVersion `
                -ExpectedInstallationId $expectedInstallationId
        }} catch {{ $rejected = $true }}
        if (-not $rejected) {{ throw "installation health accepted wrong $field" }}
    }}
    $redirectRejected = $false
    try {{
        Invoke-TicketboxDirectLoopbackHealthHttpRequest `
            -Url 'http://127.0.0.1:{server.server_port}/api/health/installation' `
            -TimeoutMilliseconds 5000 | Out-Null
    }}
    catch {{ $redirectRejected = $true }}
    if (-not $redirectRejected) {{ throw 'health redirect was followed or accepted' }}
    $oversizedRejected = $false
    try {{
        Invoke-TicketboxDirectLoopbackHealthHttpRequest `
            -Url 'http://127.0.0.1:{server.server_port}/api/health/installation' `
            -TimeoutMilliseconds 5000 | Out-Null
    }}
    catch {{ $oversizedRejected = $true }}
    if (-not $oversizedRejected) {{ throw 'oversized chunked health response was accepted' }}
    if ([TicketboxThrowingProxy]::Calls -ne 0) {{ throw 'default proxy was consulted' }}
    if ($script:listenerChecks -ne 1) {{ throw 'successful request was not post-validated' }}
}}
finally {{
    [System.Net.WebRequest]::DefaultWebProxy = $previousProxy
}}
""",
            encoding="utf-8-sig",
        )
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
            assert "proxy-bypass-test-secret" not in result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell listener revalidation contract")
def test_bootstrap_request_exception_revalidates_listener_and_stops_on_failure(
    tmp_path: Path,
) -> None:
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    with socket.socket() as closed_socket:
        closed_socket.bind(("127.0.0.1", 0))
        closed_port = closed_socket.getsockname()[1]
    harness = tmp_path / "bootstrap-request-failure.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(BOOTSTRAP_SCRIPT).replace("'", "''")}'
$script:listenerChecks = 0
$script:listenerFails = $false
function Get-TicketboxBackendListenerIdentity {{ return [pscustomobject]@{{ Id = 1 }} }}
function Assert-TicketboxBackendListenerUnchanged([object]$ExpectedIdentity) {{
    $script:listenerChecks += 1
    if ($script:listenerFails) {{ throw 'simulated listener replacement' }}
}}
$body = [System.Text.Encoding]::UTF8.GetBytes('{{}}')
$retryable = $false
try {{
    Invoke-TicketboxOwnerBootstrapHttpRequest `
        -Url 'http://127.0.0.1:{closed_port}/api/bootstrap/owner' `
        -Secret 'test-bootstrap-secret-that-must-not-be-printed' `
        -BodyBytes $body `
        -TimeoutMilliseconds 1000 | Out-Null
}}
catch {{
    $retryable = $_.Exception -isnot [System.Security.SecurityException]
}}
if (-not $retryable -or $script:listenerChecks -ne 1) {{
    throw 'request failure did not perform a retryable listener post-check'
}}
$script:listenerFails = $true
$fatal = $false
try {{
    Invoke-TicketboxOwnerBootstrapHttpRequest `
        -Url 'http://127.0.0.1:{closed_port}/api/bootstrap/owner' `
        -Secret 'test-bootstrap-secret-that-must-not-be-printed' `
        -BodyBytes $body `
        -TimeoutMilliseconds 1000 | Out-Null
}}
catch [System.Security.SecurityException] {{
    $fatal = $_.Exception.Message -match 'secret 可能已暴露'
}}
if (-not $fatal -or $script:listenerChecks -ne 2) {{
    throw 'listener post-check failure did not stop retries with an exposure warning'
}}
""",
        encoding="utf-8-sig",
    )
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
        assert "test-bootstrap-secret-that-must-not-be-printed" not in result.stdout + result.stderr
