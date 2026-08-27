from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _run_cross_engine(harness: Path, timeout: int = 60) -> None:
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell contract")
def test_service_identity_semantics_match_in_powershell_5_and_7(tmp_path: Path) -> None:
    harness = tmp_path / "service-identity-semantics.ps1"
    harness.write_text(
        rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_service_identity.ps1')}'
. '{_literal(PACKAGING / 'windows_release_config.ps1')}'

if ((Get-TicketboxServiceResourcePrincipal TicketboxPg) -cne 'NT SERVICE\TicketboxPg') {{
    throw 'resource principal was not derived from the service name'
}}
if ((ConvertTo-TicketboxServiceLogonAccount `
        -Name TicketboxPg `
        -Account 'nt authority\localservice') -cne 'NT AUTHORITY\LocalService') {{
    throw 'LocalService was not canonicalized'
}}

$legacyRejected = $false
try {{
    ConvertTo-TicketboxServiceLogonAccount `
        -Name TicketboxPg `
        -Account 'NT SERVICE\TicketboxPg' | Out-Null
}}
catch {{ $legacyRejected = $true }}
if (-not $legacyRejected) {{ throw 'legacy virtual account became current authority' }}

$legacy = ConvertTo-TicketboxServiceLogonAccount `
    -Name TicketboxPg `
    -Account 'nt service\ticketboxpg' `
    -AllowLegacyVirtualAccount
if ($legacy -cne 'NT SERVICE\TicketboxPg') {{
    throw 'explicit legacy compatibility did not preserve the canonical audit identity'
}}

foreach ($unsafe in @('LocalSystem', 'NT AUTHORITY\NetworkService', 'Machine\User')) {{
    $rejected = $false
    try {{
        ConvertTo-TicketboxServiceLogonAccount `
            -Name TicketboxPg `
            -Account $unsafe `
            -AllowLegacyVirtualAccount | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "unsafe logon account accepted: $unsafe" }}
}}

foreach ($invalidName in @('', 'Ticketbox/Pg', 'Ticketbox\Pg', ('Ticketbox' + [char]0 + 'Pg'))) {{
    $rejected = $false
    try {{ Get-TicketboxServiceResourcePrincipal $invalidName | Out-Null }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw 'invalid service name reached identity derivation' }}
}}

foreach ($sidType in @('none', 'unrestricted', 'restricted')) {{
    $value = ConvertTo-TicketboxServiceSidTypeValue $sidType
    if ((ConvertFrom-TicketboxServiceSidTypeValue $value) -cne $sidType) {{
        throw "service SID type failed round trip: $sidType"
    }}
}}

$currentConfig = Read-TicketboxWindowsReleaseConfig `
    '{_literal(PACKAGING / 'windows-release-config.json')}'
if ((Get-TicketboxReleaseServiceLogonAccount `
        -Config $currentConfig `
        -ServiceName TicketboxBackend) -cne 'NT AUTHORITY\LocalService' -or
    (Get-TicketboxReleaseServiceSidType $currentConfig) -cne 'unrestricted') {{
    throw 'current release service identity was not explicit'
}}
$legacyConfig = $currentConfig | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$legacyConfig.schema = 'ticketbox-windows-release-v1'
$legacyConfig.PSObject.Properties.Remove('service_logon_account')
$legacyConfig.PSObject.Properties.Remove('service_sid_type')
if ((Get-TicketboxReleaseServiceLogonAccount `
        -Config $legacyConfig `
        -ServiceName TicketboxBackend) -cne 'NT SERVICE\TicketboxBackend' -or
    (Get-TicketboxReleaseServiceSidType $legacyConfig) -cne 'none') {{
    throw 'legacy release was not preserved as compatibility input'
}}
if ((Get-TicketboxReleaseServiceIdentityTransition `
        -InstalledConfig $legacyConfig `
        -TargetConfig $currentConfig) -cne 'legacy_virtual_to_service_sid') {{
    throw 'known legacy-to-current transition was not classified'
}}
$transitionShapes = @(Get-TicketboxReleaseServiceIdentityShapes `
    -InstalledConfig $legacyConfig `
    -TargetConfig $currentConfig `
    -ServiceName TicketboxBackend)
$transitionKeys = @($transitionShapes | ForEach-Object {{
    "$($_.LogonAccount)|$($_.SidType)"
}})
foreach ($requiredShape in @(
    'NT SERVICE\TicketboxBackend|none',
    'NT SERVICE\TicketboxBackend|unrestricted',
    'NT AUTHORITY\LocalService|unrestricted'
)) {{
    if ($transitionKeys -notcontains $requiredShape) {{
        throw "service identity transition lost shape: $requiredShape"
    }}
}}
if ($transitionKeys.Count -ne 3 -or
    $transitionKeys -contains 'NT AUTHORITY\LocalService|none') {{
    throw 'service identity transition admitted an unprepared crash tuple'
}}
$pendingShapes = @(Get-TicketboxReleaseServiceIdentityShapes `
    -InstalledConfig $currentConfig `
    -TargetConfig $currentConfig `
    -ServiceName TicketboxBackend `
    -AllowTargetSidTypePending)
if ($pendingShapes.Count -ne 2 -or
    @($pendingShapes | ForEach-Object {{ "$($_.LogonAccount)|$($_.SidType)" }}) -notcontains
        'NT AUTHORITY\LocalService|none') {{
    throw 'receipt-authorized fresh create crash tuple was not bounded'
}}
$reverseRejected = $false
try {{
    Get-TicketboxReleaseServiceIdentityTransition `
        -InstalledConfig $currentConfig `
        -TargetConfig $legacyConfig | Out-Null
}}
catch {{ $reverseRejected = $true }}
if (-not $reverseRejected) {{ throw 'current identity was allowed to downgrade to legacy' }}
$changedCurrent = $currentConfig | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$changedCurrent.service_sid_type = 'restricted'
$unpreparedChangeRejected = $false
try {{
    Get-TicketboxReleaseServiceIdentityTransition `
        -InstalledConfig $currentConfig `
        -TargetConfig $changedCurrent | Out-Null
}}
catch {{ $unpreparedChangeRejected = $true }}
if (-not $unpreparedChangeRejected) {{
    throw 'unprepared current service identity change was accepted'
}}

$script:currentSidType = [uint32]0
$script:setCalls = @()
function Invoke-TicketboxNativeServiceSidTypeQuery([string]$Name) {{
    if ($Name -cne 'TicketboxPg') {{ throw 'query received the wrong service' }}
    return $script:currentSidType
}}
function Invoke-TicketboxNativeServiceSidTypeSet {{
    param([string]$Name, [uint32]$SidType)
    if ($Name -cne 'TicketboxPg') {{ throw 'set received the wrong service' }}
    $script:setCalls += $SidType
    $script:currentSidType = $SidType
}}
if ((Get-TicketboxServiceSidType TicketboxPg) -cne 'none') {{
    throw 'native SID type query was not normalized'
}}
Set-TicketboxServiceSidType -Name TicketboxPg -SidType restricted
if ($script:setCalls.Count -ne 1 -or $script:setCalls[0] -ne 3) {{
    throw 'restricted SID type did not reach ChangeServiceConfig2 semantics'
}}
Assert-TicketboxServiceSidType -Name TicketboxPg -ExpectedSidType restricted

$script:currentSidType = [uint32]2
$unknownRejected = $false
try {{ Get-TicketboxServiceSidType TicketboxPg | Out-Null }}
catch {{ $unknownRejected = $true }}
if (-not $unknownRejected) {{ throw 'unknown SCM SID type was accepted' }}
"SERVICE_IDENTITY_SEMANTICS_OK"
""",
        encoding="utf-8-sig",
    )
    _run_cross_engine(harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows SCM query contract")
def test_native_service_sid_type_query_is_read_only_cross_engine(tmp_path: Path) -> None:
    harness = tmp_path / "service-identity-native-query.ps1"
    harness.write_text(
        rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_service_identity.ps1')}'
$before = Get-CimInstance -ClassName Win32_Service -Filter "Name='EventLog'"
$sidType = Get-TicketboxServiceSidType EventLog
$after = Get-CimInstance -ClassName Win32_Service -Filter "Name='EventLog'"
if ($sidType -notin @('none', 'unrestricted', 'restricted')) {{
    throw "unexpected EventLog SID type: $sidType"
}}
if ($before.StartName -cne $after.StartName -or $before.StartMode -cne $after.StartMode) {{
    throw 'read-only service SID query changed SCM configuration'
}}
"SERVICE_IDENTITY_NATIVE_QUERY_OK:$sidType"
""",
        encoding="utf-8-sig",
    )
    _run_cross_engine(harness)


