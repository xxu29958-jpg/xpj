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
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.packaging_resource("hermetic")

PACKAGING = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = PACKAGING / "windows_backend_bootstrap.ps1"
SAFETY_SCRIPT = PACKAGING / "windows_installation_safety.ps1"
# Host startup plus three ACL-protected writes; keep each legal stage a 15s budget.
_PROTECTED_WRITER_CONTRACT_TIMEOUT_SECONDS = 60


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
    assert '@($Payload.PSObject.Properties).Count -ne 9' in script
    assert '$Payload.runtime_access_state -notin @("available", "repair_required")' in script
    assert '[string]$Payload.contract -cne "ticketbox-installation-health-v2"' in script
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
    assert "Write-TicketboxProtectedUtf8FileDurable" in script
    assert "Read-TicketboxProtectedUtf8Artifact" in script
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
    assert "Get-TicketboxOwnerHandoffLifecycleIdentity" in script
    handoff_writer = script[
        script.index("function Write-TicketboxOwnerHandoffMarker") :
        script.index("function Write-TicketboxOwnerHandoffPendingMarker")
    ]
    assert "Get-TicketboxOwnerHandoffLifecycleIdentity" in handoff_writer
    assert "Get-Process" not in handoff_writer
    assert script.index("Write-TicketboxOwnerHandoffPendingMarker") < script.index(
        "-Path $OwnerBootstrapPath"
    )
    persisted_owner = script.index("Write-TicketboxOwnerBootstrapFile $response")
    assert persisted_owner < script.index("Write-EnvNoBom -Path $EnvPath", persisted_owner)
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


def test_installer_state_migration_is_ordered_and_resumable_before_service_start() -> None:
    bootstrap = _read()
    install = (PACKAGING / "install_bundled_services.ps1").read_text(encoding="utf-8-sig")
    migration = bootstrap[
        bootstrap.index("function Move-TicketboxLegacyOwnerHandoffArtifacts") :
        bootstrap.index("function Read-TicketboxOwnerHandoffRecord")
    ]
    migration_calls = migration[migration.index("Initialize-TicketboxInstallerStateDirectory") :]
    assert migration_calls.index("$LegacyOwnerBootstrapPath") < migration_calls.index(
        "$LegacyOwnerHandoffPendingPath"
    )

    main = install[install.index("$operationLock = Enter-TicketboxLifecycleLock") :]
    marker = main.index("Initialize-TicketboxDataRootMarker")
    mutation = main.index("$mutationStarted = $true")
    stopped = main.index("Stop-ServiceIfExists", mutation)
    acl_reset = main.index("Initialize-TicketboxSecureDataRoot", stopped)
    migrated = main.index("Initialize-TicketboxInstallerStateArtifacts", acl_reset)
    adopted = main.index("Adopt-TicketboxOwnerBootstrapHandoff", migrated)
    service_acl = main.index("Set-TicketboxAcl", adopted)
    backend_start = main.index('Write-Step "启动后端服务"', service_acl)
    assert marker < mutation < stopped < acl_reset < migrated < adopted < service_acl < backend_start


@pytest.mark.packaging_resource("windows_fs")
@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell durable file contract")
def test_protected_writer_requires_explicit_atomic_replacement_in_powershell_5_and_7(
    tmp_path: Path,
) -> None:
    target = tmp_path / "protected-state.txt"
    harness = tmp_path / "protected-writer.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(SAFETY_SCRIPT).replace("'", "''")}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$target = '{str(target).replace("'", "''")}'
$originalMove = ${{function:Move-TicketboxFileDurable}}
$script:prePublishAclVerified = $false
function Move-TicketboxFileDurable([string]$Source, [string]$Destination, [switch]$ReplaceExisting) {{
    Assert-TicketboxExactFileAcl `
        -Path $Source `
        -Accounts @($currentAccount) `
        -OwnerAccount $currentAccount
    $expectedOwner = ConvertTo-TicketboxAccountSid $currentAccount
    $actualOwner = ConvertTo-TicketboxAccountSid (Get-TicketboxPathAcl $Source).Owner
    if ($actualOwner -ne $expectedOwner) {{ throw 'temporary file owner was not final before publish' }}
    $script:prePublishAclVerified = $true
    & $originalMove $Source $Destination -ReplaceExisting:$ReplaceExisting
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path $target `
    -Text 'pending' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$createNewRejected = $false
try {{
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $target `
        -Text 'must-not-overwrite' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $createNewRejected = $true }}
if (-not $createNewRejected) {{ throw 'protected writer replaced an existing file without opt-in' }}
if ([System.IO.File]::ReadAllText($target) -cne 'pending') {{ throw 'failed CreateNew changed the target' }}
Write-TicketboxProtectedUtf8FileDurable `
    -Path $target `
    -Text 'confirmed' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount `
    -ReplaceExisting
if ([System.IO.File]::ReadAllText($target) -cne 'confirmed') {{ throw 'explicit replacement was not published' }}
if (-not $script:prePublishAclVerified) {{ throw 'temporary ACL was not verified before publish' }}
if (@(Get-ChildItem -LiteralPath '{str(tmp_path).replace("'", "''")}' -Filter '.ticketbox-protected-*.tmp').Count -ne 0) {{
    throw 'protected writer left a temporary file'
}}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        target.unlink(missing_ok=True)
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PROTECTED_WRITER_CONTRACT_TIMEOUT_SECONDS,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.packaging_resource("windows_fs")
@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell installer-state ACL contract")
def test_installer_state_migration_survives_recursive_app_acl_reset_in_powershell_5_and_7(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "installer-state-migration.ps1"
    root = tmp_path / "data"
    app = root / "app"
    lifecycle_root = tmp_path / "machine-lifecycle"
    installer_state = lifecycle_root / "installer-state"
    legacy_credential = app / "owner-bootstrap.txt"
    current_credential = installer_state / "owner-bootstrap.txt"
    legacy_marker = app / "owner-handoff-pending"
    current_marker = installer_state / "owner-handoff-pending"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(SAFETY_SCRIPT).replace("'", "''")}'
. '{str(PACKAGING / "windows_lifecycle_lock.ps1").replace("'", "''")}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$root = '{str(root).replace("'", "''")}'
$app = '{str(app).replace("'", "''")}'
$lifecycleRoot = '{str(lifecycle_root).replace("'", "''")}'
$installerState = '{str(installer_state).replace("'", "''")}'
$legacyCredential = '{str(legacy_credential).replace("'", "''")}'
$currentCredential = '{str(current_credential).replace("'", "''")}'
$legacyMarker = '{str(legacy_marker).replace("'", "''")}'
$currentMarker = '{str(current_marker).replace("'", "''")}'
$backendAccount = 'NT AUTHORITY\\LOCAL SERVICE'
New-Item -ItemType Directory -Path $app -Force | Out-Null
New-Item -ItemType Directory -Path $lifecycleRoot -Force | Out-Null
Set-TicketboxExactDirectoryAcl `
    -Path $lifecycleRoot `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$testLockRoot = Join-Path $lifecycleRoot 'lock-root'
Initialize-TicketboxLifecycleLockDirectory `
    -LockDirectory $testLockRoot `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
Assert-TicketboxProtectedDirectoryAcl `
    -Path $testLockRoot `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$latch = Join-Path $testLockRoot 'existing-latch.json'
Write-TicketboxProtectedUtf8FileDurable `
    -Path $latch `
    -Text 'must-survive-root-drift' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$backendSidForDrift = ConvertTo-TicketboxAccountSid $backendAccount
Invoke-TicketboxIcaclsChecked $testLockRoot @('/grant', "*${{backendSidForDrift}}:(OI)(CI)F")
$driftedRootSddl = (Get-TicketboxPathAcl $testLockRoot).Sddl
$rootDriftRejected = $false
try {{
    Initialize-TicketboxLifecycleLockDirectory `
        -LockDirectory $testLockRoot `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
catch {{ $rootDriftRejected = $true }}
if (-not $rootDriftRejected -or
    (Get-TicketboxPathAcl $testLockRoot).Sddl -cne $driftedRootSddl -or
    [System.IO.File]::ReadAllText($latch) -cne 'must-survive-root-drift') {{
    throw 'existing lifecycle root drift was normalized or its state was changed'
}}
$junctionTarget = Join-Path $lifecycleRoot 'lock-junction-target'
$junctionRoot = Join-Path $lifecycleRoot 'lock-junction'
New-Item -ItemType Directory -Path $junctionTarget -Force | Out-Null
[System.IO.File]::WriteAllText((Join-Path $junctionTarget 'sentinel.txt'), 'must-not-change')
& cmd.exe /d /c "mklink /J `"$junctionRoot`" `"$junctionTarget`"" | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw 'could not create lifecycle root junction fixture' }}
$junctionRejected = $false
try {{
    Initialize-TicketboxLifecycleLockDirectory `
        -LockDirectory $junctionRoot `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
catch {{ $junctionRejected = $true }}
if (-not $junctionRejected -or
    [System.IO.File]::ReadAllText((Join-Path $junctionTarget 'sentinel.txt')) -cne 'must-not-change' -or
    (Test-Path -LiteralPath (Join-Path $junctionTarget 'installer-lifecycle.lock')) -or
    (Test-Path -LiteralPath (Join-Path $junctionTarget 'installer-lifecycle.owner'))) {{
    throw 'lifecycle root junction was followed or mutated before authority validation'
}}
[System.IO.Directory]::Delete($junctionRoot)
Set-TicketboxExactDirectoryAcl `
    -Path $root `
    -Accounts @($currentAccount) `
    -ReadExecuteAccounts @($backendAccount) `
    -OwnerAccount $currentAccount
Set-TicketboxExactDirectoryAcl `
    -Path $app `
    -Accounts @($currentAccount, $backendAccount) `
    -OwnerAccount $currentAccount `
    -Recurse
Write-TicketboxProtectedUtf8FileDurable `
    -Path $legacyCredential `
    -Text 'credential-v1' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Write-TicketboxProtectedUtf8FileDurable `
    -Path $legacyMarker `
    -Text 'pending-state' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Initialize-TicketboxInstallerStateDirectory `
    -Path $installerState `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $legacyCredential `
    -CurrentPath $currentCredential `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $legacyMarker `
    -CurrentPath $currentMarker `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$aclBefore = (Get-TicketboxPathAcl $currentMarker).Sddl
New-Item -ItemType File -Path (Join-Path $app 'backend-owned.tmp') -Force | Out-Null
Set-TicketboxExactDirectoryAcl `
    -Path $app `
    -Accounts @($currentAccount, $backendAccount) `
    -OwnerAccount $currentAccount `
    -Recurse
$aclAfter = (Get-TicketboxPathAcl $currentMarker).Sddl
if ((Test-Path -LiteralPath $legacyCredential) -or (Test-Path -LiteralPath $legacyMarker)) {{
    throw 'legacy handoff artifact survived migration'
}}
if ([System.IO.File]::ReadAllText($currentCredential) -cne 'credential-v1') {{
    throw 'migrated credential content changed'
}}
if ([System.IO.File]::ReadAllText($currentMarker) -cne 'pending-state') {{
    throw 'migrated marker content changed'
}}
if ($aclBefore -cne $aclAfter) {{ throw 'recursive app ACL reset changed sibling installer-state ACL' }}
Assert-TicketboxExactFileAcl `
    -Path $currentMarker `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
$backendSid = (New-Object Security.Principal.NTAccount($backendAccount)).Translate(
    [Security.Principal.SecurityIdentifier]
).Value
foreach ($rule in (Get-TicketboxPathAcl $installerState).Access) {{
    $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($sid -eq $backendSid) {{ throw 'backend principal reached installer-state ACL' }}
}}
foreach ($rule in (Get-TicketboxPathAcl $root).Access) {{
    $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($sid -ne $backendSid) {{ continue }}
    $forbidden = (
        [Security.AccessControl.FileSystemRights]::CreateFiles -bor
        [Security.AccessControl.FileSystemRights]::CreateDirectories -bor
        [Security.AccessControl.FileSystemRights]::Delete -bor
        [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    )
    if (($rule.FileSystemRights -band $forbidden) -ne 0) {{
        throw 'backend principal retained create/delete authority at data-root parent'
    }}
}}

# Crash after credential move: current credential + legacy marker must converge.
Remove-Item -LiteralPath $currentMarker -Force
Write-TicketboxProtectedUtf8FileDurable `
    -Path $legacyMarker `
    -Text 'pending-v2' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $legacyCredential `
    -CurrentPath $currentCredential `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $legacyMarker `
    -CurrentPath $currentMarker `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
if ([System.IO.File]::ReadAllText($currentMarker) -cne 'pending-v2') {{
    throw 'credential-first crash state did not converge'
}}

# Existing marker + legacy credential is also resumable and keeps marker authority.
Remove-Item -LiteralPath $currentCredential -Force
Write-TicketboxProtectedUtf8FileDurable `
    -Path $legacyCredential `
    -Text 'credential-v3' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $legacyCredential `
    -CurrentPath $currentCredential `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $legacyMarker `
    -CurrentPath $currentMarker `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
if ([System.IO.File]::ReadAllText($currentCredential) -cne 'credential-v3' -or
    [System.IO.File]::ReadAllText($currentMarker) -cne 'pending-v2') {{
    throw 'marker-first crash state did not converge'
}}

# Crash after destination publication: identical old/new files converge by deleting legacy.
Write-TicketboxProtectedUtf8FileDurable `
    -Path $legacyCredential `
    -Text 'credential-v3' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $legacyCredential `
    -CurrentPath $currentCredential `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
if (Test-Path -LiteralPath $legacyCredential) {{
    throw 'identical dual-location crash state did not converge'
}}

# Divergent dual-location state must fail closed and preserve both artifacts.
Write-TicketboxProtectedUtf8FileDurable `
    -Path $legacyCredential `
    -Text 'conflicting-credential' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$conflictRejected = $false
try {{
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $legacyCredential `
        -CurrentPath $currentCredential `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $conflictRejected = $true }}
if (-not $conflictRejected -or
    -not (Test-Path -LiteralPath $legacyCredential -PathType Leaf) -or
    -not (Test-Path -LiteralPath $currentCredential -PathType Leaf)) {{
    throw 'conflicting dual-location state did not fail closed'
}}
Remove-Item -LiteralPath $legacyCredential -Force

# A directory or reparse-like non-file at either path is corruption, not absence.
New-Item -ItemType Directory -Path $legacyCredential | Out-Null
$nonFileRejected = $false
try {{
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $legacyCredential `
        -CurrentPath $currentCredential `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $nonFileRejected = $true }}
if (-not $nonFileRejected) {{ throw 'legacy directory was treated as an absent artifact' }}
Remove-Item -LiteralPath $legacyCredential -Force

$currentSid = ConvertTo-TicketboxAccountSid $currentAccount
Invoke-TicketboxIcaclsChecked $installerState @('/remove:g', "*${{currentSid}}")
Invoke-TicketboxIcaclsChecked $installerState @('/grant:r', "*${{currentSid}}:F")
$malformedFlagsRejected = $false
try {{
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $installerState `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
catch {{ $malformedFlagsRejected = $true }}
if (-not $malformedFlagsRejected) {{
    throw 'non-inheritable allowed-SID FullControl passed the exact directory ACL contract'
}}
Set-TicketboxExactDirectoryAcl `
    -Path $installerState `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount

$protectedStage = Join-Path $installerState '.ticketbox-protected-11111111111111111111111111111111.tmp'
$durableStage = Join-Path $installerState '.ticketbox-durable-22222222222222222222222222222222.tmp'
$unrelatedStage = Join-Path $installerState '.ticketbox-protected-not-a-guid.tmp'
Set-Content -LiteralPath $protectedStage -Value 'pre-acl-crash'
Write-TicketboxProtectedUtf8FileDurable `
    -Path $durableStage `
    -Text 'post-acl-crash' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
Set-Content -LiteralPath $unrelatedStage -Value 'must-remain-unknown'
Initialize-TicketboxInstallerStateDirectory `
    -Path $installerState `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
if ((Test-Path $protectedStage) -or (Test-Path $durableStage) -or
    -not (Test-Path $unrelatedStage -PathType Leaf)) {{
    throw 'installer-state staging cleanup did not distinguish owned namespaces'
}}
Remove-Item -LiteralPath $unrelatedStage -Force

Set-TicketboxExactDirectoryAcl `
    -Path $installerState `
    -Accounts @($currentAccount, $backendAccount) `
    -OwnerAccount $currentAccount
$driftRejected = $false
try {{
    Initialize-TicketboxInstallerStateDirectory `
        -Path $installerState `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
catch {{ $driftRejected = $true }}
if (-not $driftRejected) {{
    throw 'existing installer-state ACL drift was normalized instead of rejected'
}}

Remove-Item -LiteralPath $installerState -Recurse -Force
$junctionTarget = Join-Path $lifecycleRoot 'installer-state-target'
New-Item -ItemType Directory -Path $junctionTarget | Out-Null
Set-TicketboxExactDirectoryAcl `
    -Path $junctionTarget `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Set-Content -LiteralPath (Join-Path $junctionTarget 'keep.txt') -Value 'keep'
& cmd.exe /d /c "mklink /J `"$installerState`" `"$junctionTarget`"" | Out-Null
if ($LASTEXITCODE -eq 0) {{
    $junctionRejected = $false
    try {{
        Initialize-TicketboxInstallerStateDirectory `
            -Path $installerState `
            -FullControlAccounts @($currentAccount) `
            -OwnerAccount $currentAccount | Out-Null
    }}
    catch {{ $junctionRejected = $true }}
    if (-not $junctionRejected -or
        -not (Test-Path -LiteralPath (Join-Path $junctionTarget 'keep.txt') -PathType Leaf)) {{
        throw 'installer-state junction was accepted or its target was mutated'
    }}
    [System.IO.Directory]::Delete($installerState)
}}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(lifecycle_root, ignore_errors=True)
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


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell owner migration provenance contract")
def test_legacy_credential_only_migration_binds_before_retiring_source(tmp_path: Path) -> None:
    harness = tmp_path / "owner-legacy-provenance.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(SAFETY_SCRIPT).replace("'", "''")}'
. '{str(BOOTSTRAP_SCRIPT).replace("'", "''")}'
$InstallerState = '{str(tmp_path / 'installer-state').replace("'", "''")}'
$OwnerBootstrapPath = Join-Path $InstallerState 'owner-bootstrap.txt'
$OwnerHandoffPendingPath = Join-Path $InstallerState 'owner-handoff-pending'
$LegacyRoot = '{str(tmp_path / 'legacy').replace("'", "''")}'
$LegacyOwnerBootstrapPath = Join-Path $LegacyRoot 'owner-bootstrap.txt'
$LegacyOwnerHandoffPendingPath = Join-Path $LegacyRoot 'owner-handoff-pending'
$InstallDir = '{str(tmp_path / 'program').replace("'", "''")}'
$DataRoot = '{str(tmp_path / 'data').replace("'", "''")}'
$InstallerLockOwnerProcessId = $PID
function Get-TicketboxValidatedExternalLifecycleOwnerIdentity([int]$OwnerProcessId) {{
    $process = Get-Process -Id $OwnerProcessId -ErrorAction Stop
    return [pscustomobject]@{{
        ProcessId = $OwnerProcessId
        StartedUtc = $process.StartTime.ToUniversalTime().ToString(
            'yyyy-MM-ddTHH:mm:ss.fffffffZ',
            [Globalization.CultureInfo]::InvariantCulture
        )
    }}
}}
New-Item -ItemType Directory -Path $LegacyRoot, $InstallDir, $DataRoot -Force | Out-Null
function Initialize-TicketboxInstallerStateDirectory {{
    param($Path, $FullControlAccounts, $OwnerAccount)
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    return $Path
}}
function Assert-TicketboxProtectedDirectoryAcl {{ param($Path, $FullControlAccounts, $OwnerAccount) }}
function Assert-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function Assert-NoTicketboxAncestorReparsePoints {{ param($Path) }}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $OwnerAccount, $MaximumBytes = 65536)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{ throw 'artifact is not a file' }}
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -le 0 -or $bytes.Length -gt $MaximumBytes) {{ throw 'artifact size invalid' }}
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    return [pscustomobject]@{{ Text = $encoding.GetString($bytes); Bytes = $bytes }}
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    if ((Test-Path -LiteralPath $Path) -and -not $ReplaceExisting) {{ throw 'CreateNew collision' }}
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}}
function Remove-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $OwnerAccount)
    Read-TicketboxProtectedUtf8Artifact -Path $Path | Out-Null
    Remove-Item -LiteralPath $Path -Force
}}
[System.IO.File]::WriteAllText($LegacyOwnerBootstrapPath, 'legacy-owner-credential')

# Simulate a crash immediately after current credential publication.
Initialize-TicketboxInstallerStateDirectory $InstallerState | Out-Null
Move-TicketboxLegacyInstallerStateArtifact `
    -LegacyPath $LegacyOwnerBootstrapPath `
    -CurrentPath $OwnerBootstrapPath `
    -RetainLegacySource
if (-not (Test-Path $LegacyOwnerBootstrapPath) -or -not (Test-Path $OwnerBootstrapPath)) {{
    throw 'migration source proof was retired before marker binding'
}}
Move-TicketboxLegacyOwnerHandoffArtifacts `
    -InstallerStatePath $InstallerState `
    -LegacyOwnerBootstrapPath $LegacyOwnerBootstrapPath `
    -LegacyOwnerHandoffPendingPath $LegacyOwnerHandoffPendingPath
if ((Test-Path $LegacyOwnerBootstrapPath) -or -not (Test-Path $OwnerHandoffPendingPath)) {{
    throw 'legacy-only credential did not converge to a bound current handoff'
}}
$record = Read-TicketboxOwnerHandoffRecord
Assert-TicketboxOwnerHandoffCredential $record
if ($record.State -cne 'pending' -or $record.OwnerProcessId -ne $PID) {{
    throw 'migrated handoff binding is not owned by the current installer'
}}

# Malformed sibling state is preflighted before the credential can move.
Remove-Item -LiteralPath $InstallerState -Recurse -Force
New-Item -ItemType Directory -Path $InstallerState -Force | Out-Null
[System.IO.File]::WriteAllText($LegacyOwnerBootstrapPath, 'second-legacy-credential')
New-Item -ItemType Directory -Path $LegacyOwnerHandoffPendingPath | Out-Null
$preflightRejected = $false
try {{
    Move-TicketboxLegacyOwnerHandoffArtifacts `
        -InstallerStatePath $InstallerState `
        -LegacyOwnerBootstrapPath $LegacyOwnerBootstrapPath `
        -LegacyOwnerHandoffPendingPath $LegacyOwnerHandoffPendingPath
}}
catch {{ $preflightRejected = $true }}
if (-not $preflightRejected -or (Test-Path -LiteralPath $OwnerBootstrapPath)) {{
    throw 'owner migration mutated credential before preflighting all legacy artifacts'
}}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        shutil.rmtree(tmp_path / "installer-state", ignore_errors=True)
        shutil.rmtree(tmp_path / "legacy", ignore_errors=True)
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


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell owner handoff canonical parser")
def test_owner_handoff_parser_rejects_noncanonical_equivalent_authority(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "owner-handoff-canonical-parser.ps1"
    generation = "22222222-2222-4222-8222-222222222222"
    installation_id = "11111111-1111-4111-8111-111111111111"
    credential_hash = "a" * 64
    canonical_time = "2026-07-12T01:02:03.1234567Z"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(BOOTSTRAP_SCRIPT).replace("'", "''")}'
$OwnerHandoffPendingPath = 'unused-owner-handoff-path'
function Read-TicketboxOwnerHandoffArtifact {{
    param($Path)
    return [pscustomobject]@{{ Text = $script:recordText }}
}}
function Get-TicketboxOwnerHandoffInstallationId {{ return '{installation_id}' }}
function Set-TestRecord([string]$Generation, [string]$OwnerPid, [string]$StartedUtc) {{
    $script:recordText =
        "SCHEMA=ticketbox-owner-handoff-v2$([Environment]::NewLine)" +
        "STATE=pending$([Environment]::NewLine)" +
        "GENERATION=$Generation$([Environment]::NewLine)" +
        "INSTALLATION_ID={installation_id}$([Environment]::NewLine)" +
        "CREDENTIAL_SHA256={credential_hash}$([Environment]::NewLine)" +
        "INSTALLER_OWNER_PID=$OwnerPid$([Environment]::NewLine)" +
        "INSTALLER_OWNER_STARTED_UTC=$StartedUtc$([Environment]::NewLine)"
}}
function Assert-TestRecordRejected([string]$Generation, [string]$OwnerPid, [string]$StartedUtc) {{
    Set-TestRecord $Generation $OwnerPid $StartedUtc
    $before = $script:recordText
    $rejected = $false
    try {{ Read-TicketboxOwnerHandoffRecord | Out-Null }}
    catch {{ $rejected = $true }}
    if (-not $rejected -or $script:recordText -cne $before) {{
        throw 'noncanonical owner handoff authority was accepted or mutated'
    }}
}}
Set-TestRecord '{generation}' '123' '{canonical_time}'
$valid = Read-TicketboxOwnerHandoffRecord
if ($valid.Generation -cne '{generation}' -or
    $valid.OwnerProcessId -ne 123 -or
    $valid.OwnerStartedUtc -cne '{canonical_time}') {{
    throw 'canonical owner handoff record did not round-trip'
}}
Assert-TestRecordRejected '{{{generation}}}' '123' '{canonical_time}'
Assert-TestRecordRejected '{generation}' '+123' '{canonical_time}'
Assert-TestRecordRejected '{generation}' '123' '2026-07-12T01:02:03.1234567+00:00'
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
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
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    $temporary = "$Path.tmp"
    [System.IO.File]::WriteAllText($temporary, $Text, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $Path -Force:$ReplaceExisting
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
    engines = powershell_contract_engines()
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
$validatedLifecycleStartedUtc = '2001-02-03T04:05:06.0000000Z'
function Get-TicketboxValidatedExternalLifecycleOwnerIdentity([int]$OwnerProcessId) {{
    return [pscustomobject]@{{
        ProcessId = $OwnerProcessId
        StartedUtc = $validatedLifecycleStartedUtc
    }}
}}
$script:rejectMarkerAcl = $false
$script:crashBeforeMarkerDeletion = $false
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{ }}
function Assert-TicketboxProtectedDirectoryAcl([string]$Path) {{ }}
function ConvertTo-TicketboxCanonicalPath([string]$Path) {{ return [IO.Path]::GetFullPath($Path) }}
function Assert-TicketboxExactFileAcl {{
    param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount)
    if ($script:rejectMarkerAcl -and $Path -ceq $OwnerHandoffPendingPath) {{
        throw 'simulated marker ACL substitution'
    }}
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $OwnerAccount, $MaximumBytes)
    Assert-TicketboxExactFileAcl -Path $Path
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    return [pscustomobject]@{{ Text = $text; Bytes = [System.Text.Encoding]::UTF8.GetBytes($text) }}
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    $temporary = "$Path.tmp"
    [System.IO.File]::WriteAllText($temporary, $Text, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $Path -Force:$ReplaceExisting
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
$initialRecord = Read-TicketboxOwnerHandoffRecord
if ($initialRecord.OwnerStartedUtc -cne $validatedLifecycleStartedUtc) {{
    throw 'owner marker re-read PID StartTime instead of using validated lifecycle identity'
}}
$script:rejectMarkerAcl = $true
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


@pytest.mark.packaging_resource("windows_host")
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
function Get-TicketboxValidatedExternalLifecycleOwnerIdentity([int]$OwnerProcessId) {{
    $process = Get-Process -Id $OwnerProcessId -ErrorAction Stop
    return [pscustomobject]@{{
        ProcessId = $OwnerProcessId
        StartedUtc = $process.StartTime.ToUniversalTime().ToString(
            'yyyy-MM-ddTHH:mm:ss.fffffffZ',
            [Globalization.CultureInfo]::InvariantCulture
        )
    }}
}}
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{ }}
function Assert-TicketboxProtectedDirectoryAcl([string]$Path) {{ }}
function Assert-TicketboxExactFileAcl {{ param($Path, $Accounts, $ReadExecuteAccounts, $OwnerAccount) }}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $OwnerAccount, $MaximumBytes)
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    return [pscustomobject]@{{ Text = $text; Bytes = [System.Text.Encoding]::UTF8.GetBytes($text) }}
}}
function ConvertTo-TicketboxCanonicalPath([string]$Path) {{ return [IO.Path]::GetFullPath($Path) }}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    if ((Test-Path -LiteralPath $Path) -and -not $ReplaceExisting) {{
        throw 'target already exists'
    }}
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
$uncertainOwnerAlive = Test-TicketboxOwnerHandoffProcessIsAlive `
    -Record $current `
    -ProcessReader {{ [pscustomobject]@{{ ProcessId = $current.OwnerProcessId }} }} `
    -StartedUtcReader {{ throw 'simulated StartTime access denied after PID reuse' }}
if ($uncertainOwnerAlive) {{ throw 'unverifiable reused PID retained stale owner authority' }}
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

# Crash after credential persistence but before .env retirement resumes without replaying bootstrap.
$credential = 'persisted-owner-credential'
[System.IO.File]::WriteAllText($OwnerBootstrapPath, $credential)
$script:InstallerLockOwnerProcessId = $currentInstallerPid
Write-TicketboxOwnerHandoffMarker `
    -State 'pending' `
    -Generation ([Guid]::NewGuid().ToString('D')) `
    -CredentialSha256 (Get-TicketboxOwnerHandoffTextSha256 $credential)
$script:httpCalls = 0
$script:envWrites = 0
$script:restartCalls = 0
$script:healthCalls = 0
$BackendServiceName = 'TicketboxBackend'
$BackendPort = 8000
$BackendExe = 'backend.exe'
$ShawlExe = 'shawl.exe'
$ServiceWaitArguments = @{{}}
function Read-EnvMap([string]$Path) {{ return @{{ HTTP_BOOTSTRAP_SECRET = 'secret-still-present' }} }}
function New-BaseEnvLines([string]$DatabaseUrl) {{ return @('DATABASE_URL=postgresql://local/test') }}
function Write-EnvNoBom {{ param($Path, $Lines) $script:envWrites++ }}
function Write-Ok([string]$Message) {{ }}
function Get-ExpectedServiceExecutable([string]$Name) {{ return $ShawlExe }}
function Restart-TicketboxOwnedServiceIfExists {{
    param($Name, $ExpectedExecutable, $BackendPort, $ExpectedRuntimeExecutables)
    $script:restartCalls++
}}
function Wait-BackendHealth {{ $script:healthCalls++ }}
function Invoke-TicketboxOwnerBootstrapHttpRequest {{
    $script:httpCalls++
    throw 'bootstrap HTTP must not be replayed'
}}
Complete-FirstOwnerBootstrapIfEnabled 'postgresql://local/test'
if ($script:httpCalls -ne 0 -or $script:envWrites -ne 1 -or
    $script:restartCalls -ne 1 -or $script:healthCalls -ne 1) {{
    throw 'persisted owner handoff did not resume through secret retirement only'
}}
if (-not (Test-Path $OwnerBootstrapPath) -or -not (Test-Path $OwnerHandoffPendingPath)) {{
    throw 'resumed pending handoff was removed before user confirmation'
}}
Complete-TicketboxOwnerBootstrapHandoff

# A current-location credential without migration provenance is corruption, not legacy state.
[System.IO.File]::WriteAllText($OwnerBootstrapPath, 'unbound-current-credential')
$unboundRejected = $false
try {{ Adopt-TicketboxOwnerBootstrapHandoff | Out-Null }} catch {{ $unboundRejected = $true }}
if (-not $unboundRejected -or -not (Test-Path -LiteralPath $OwnerBootstrapPath -PathType Leaf)) {{
    throw 'unbound current credential was accepted or deleted'
}}
Remove-Item -LiteralPath $OwnerBootstrapPath -Force
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
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell cross-runtime contract")
def test_bootstrap_hmac_vector_matches_backend_in_powershell_5_and_7(tmp_path: Path) -> None:
    engines = powershell_contract_engines()
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
def test_backend_health_schema_is_consumed_by_ps51_and_ps7(tmp_path: Path) -> None:
    from app.schemas import (
        InstallationHealthResponse,
        InstallationMobileCapabilitiesResponse,
    )

    payload_path = tmp_path / "installation-health.json"
    payload_path.write_text(
        InstallationHealthResponse(
            backend_version="7.8.9",
            installation_id="ticketbox-contract-integration",
            runtime_access_state="repair_required",
            owner_state="configured",
            owner_recovery_channel="managed_host",
            mobile_connectivity=InstallationMobileCapabilitiesResponse(
                mobile_endpoint_state="local_only",
                android_binding_state="setup_required",
                iphone_upload_state="setup_required",
            ),
        ).model_dump_json(),
        encoding="utf-8",
    )
    harness = tmp_path / "installation-health-contract.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{str(BOOTSTRAP_SCRIPT).replace("'", "''")}'
$payload = Get-Content -LiteralPath '{str(payload_path).replace("'", "''")}' -Raw | ConvertFrom-Json
Assert-TicketboxInstallationHealthResponse `
    -Payload $payload `
    -ExpectedBackendVersion '7.8.9' `
    -ExpectedInstallationId 'ticketbox-contract-integration'
""",
        encoding="utf-8-sig",
    )

    for engine in powershell_contract_engines():
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


@pytest.mark.packaging_resource("windows_host")
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
                        "contract": "ticketbox-installation-health-v2",
                        "status": "ok",
                        "product": "ticketbox",
                        "backend_version": "7.8.9",
                        "installation_id": expected_installation_id,
                        "runtime_access_state": "repair_required",
                        "owner_state": "configured",
                        "owner_recovery_channel": "managed_host",
                        "mobile_connectivity": {
                            "mobile_endpoint_state": "local_only",
                            "android_binding_state": "setup_required",
                            "iphone_upload_state": "setup_required",
                        },
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
        engines = powershell_contract_engines()
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
    foreach ($field in @(
        'contract',
        'status',
        'product',
        'backend_version',
        'installation_id',
        'runtime_access_state',
        'owner_state',
        'owner_recovery_channel'
    )) {{
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
    $invalidMobile = $health.PSObject.Copy()
    $invalidMobile.mobile_connectivity = [pscustomobject]@{{
        mobile_endpoint_state = 'local_only'
        android_binding_state = 'configured_unverified'
        iphone_upload_state = 'setup_required'
    }}
    $mobileRejected = $false
    try {{
        Assert-TicketboxInstallationHealthResponse `
            -Payload $invalidMobile `
            -ExpectedBackendVersion $expectedVersion `
            -ExpectedInstallationId $expectedInstallationId
    }} catch {{ $mobileRejected = $true }}
    if (-not $mobileRejected) {{ throw 'installation health accepted invalid mobile state' }}
    $validPublic = $health.PSObject.Copy()
    $validPublic.mobile_connectivity = [pscustomobject]@{{
        mobile_endpoint_state = 'public_configured_unverified'
        android_binding_state = 'configured_unverified'
        iphone_upload_state = 'configured_unverified'
    }}
    Assert-TicketboxInstallationHealthResponse `
        -Payload $validPublic `
        -ExpectedBackendVersion $expectedVersion `
        -ExpectedInstallationId $expectedInstallationId
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


@pytest.mark.packaging_resource("windows_host")
@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell listener revalidation contract")
def test_bootstrap_request_exception_revalidates_listener_and_stops_on_failure(
    tmp_path: Path,
) -> None:
    engines = powershell_contract_engines()
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
