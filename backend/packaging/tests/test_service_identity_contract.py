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


def test_service_identity_is_a_separate_packaged_contract() -> None:
    identity = _read("windows_service_identity.ps1")
    lifecycle = _read("windows_service_lifecycle.ps1")
    build = _read("build_inno_installer.ps1")
    installer = _read("ticketbox-installer.iss")
    bootstrap = _read("ticketbox-installer-windows.isph")
    install = _read("install_bundled_services.ps1")
    prepare = _read("prepare_bundled_upgrade.ps1")
    receipt = _read("windows_lifecycle_receipt.ps1")
    provenance = (PACKAGING.parent / "scripts" / "windows_build_provenance.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert len(identity.splitlines()) < 500
    assert "NT AUTHORITY\\LocalService" in identity
    assert "SERVICE_CONFIG_SERVICE_SID_INFO = 5" in identity
    assert "QueryServiceConfig2" in identity
    assert "ChangeServiceConfig2" in identity
    assert "qsidtype" not in identity.lower()
    assert "sc.exe sidtype" not in identity.lower()
    assert lifecycle.index("windows_service_identity.ps1") < lifecycle.index(
        "windows_service_contract.ps1"
    )
    assert "ConvertTo-TicketboxServiceLogonAccount" in lifecycle
    assert "-AllowLegacyVirtualAccount" not in lifecycle
    assert '$ServiceIdentityScript = Join-Path $ScriptDir "windows_service_identity.ps1"' in build
    assert "/DServiceIdentityScriptSha256=" in build
    assert installer.count('Source: "windows_service_identity.ps1"') == 2
    assert "ServiceIdentityScriptSha256" in installer
    assert bootstrap.count("'windows_service_identity.ps1'") == 3
    assert '"packaging\\windows_service_identity.ps1"' in provenance
    converted_pg = install[
        install.index("if (Test-TicketboxPathEquals $actualExecutable $ShawlExe)") :
        install.index("elseif (Test-TicketboxPathEquals $actualExecutable $PgCtl)")
    ]
    assert converted_pg.index("Set-TicketboxServiceIdentityContract") > converted_pg.index(
        '"binPath=", $pgImagePath'
    )
    assert '"obj="' not in converted_pg[: converted_pg.index("Set-TicketboxServiceIdentityContract")]
    interrupted_commit = prepare[
        prepare.index("function Complete-TicketboxInterruptedInitdbServiceCommit") :
        prepare.index("function Invoke-TicketboxInterruptedInitdbServiceRecovery")
    ]
    assert '"obj="' not in interrupted_commit
    assert "Set-TicketboxServiceIdentityContract" in interrupted_commit
    assert "Test-TicketboxLifecycleReceiptAuthorizesServiceSidPending" in receipt


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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell contract")
def test_service_identity_transition_is_sid_first_and_retryable_cross_engine(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "service-identity-transition.ps1"
    harness.write_text(
        rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_release_config.ps1')}'
. '{_literal(PACKAGING / 'windows_service_lifecycle.ps1')}'

$currentConfig = Read-TicketboxWindowsReleaseConfig `
    '{_literal(PACKAGING / 'windows-release-config.json')}'
$legacyConfig = $currentConfig | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$legacyConfig.schema = 'ticketbox-windows-release-v1'
$legacyConfig.PSObject.Properties.Remove('service_logon_account')
$legacyConfig.PSObject.Properties.Remove('service_sid_type')

$script:account = 'NT SERVICE\TicketboxPg'
$script:sidType = 'none'
$script:calls = @()
$script:failAfterSidPublish = $false
function Get-TicketboxServiceIdentitySnapshot {{
    param([string]$Name)
    return [pscustomobject]@{{
        Name = $Name
        LogonAccount = $script:account
        SidType = $script:sidType
    }}
}}
function Set-TicketboxServiceSidType {{
    param([string]$Name,[string]$SidType)
    $script:calls += "sid:$SidType"
    $script:sidType = $SidType
    if ($script:failAfterSidPublish) {{
        $script:failAfterSidPublish = $false
        throw 'fault after SID publish'
    }}
}}
function Invoke-TicketboxScChecked {{
    param([string[]]$ScArgs)
    if (($ScArgs -join '|') -cne
        'config|TicketboxPg|obj=|NT AUTHORITY\LocalService') {{
        throw "unexpected sc.exe call: $($ScArgs -join '|')"
    }}
    $script:calls += "account:$($ScArgs[3])"
    $script:account = [string]$ScArgs[3]
}}
function Assert-TicketboxServiceIdentityShape {{
    param([string]$Name,[object[]]$AllowedShapes)
    $actual = Get-TicketboxServiceIdentitySnapshot $Name
    foreach ($shape in $AllowedShapes) {{
        if ($actual.LogonAccount -ieq $shape.LogonAccount -and
            $actual.SidType -ceq $shape.SidType) {{ return $actual }}
    }}
    throw "identity shape rejected: $($actual.LogonAccount)|$($actual.SidType)"
}}

Set-TicketboxServiceIdentityContract `
    -Name TicketboxPg `
    -LogonAccount 'NT AUTHORITY\LocalService' `
    -SidType unrestricted
if (($script:calls -join ',') -cne
    'sid:unrestricted,account:NT AUTHORITY\LocalService') {{
    throw "identity transition was not SID-first: $($script:calls -join ',')"
}}

$script:account = 'NT SERVICE\TicketboxPg'
$script:sidType = 'none'
$script:calls = @()
$script:failAfterSidPublish = $true
$faultObserved = $false
try {{
    Set-TicketboxServiceIdentityContract `
        -Name TicketboxPg `
        -LogonAccount 'NT AUTHORITY\LocalService' `
        -SidType unrestricted
}}
catch {{ $faultObserved = $true }}
if (-not $faultObserved -or
    $script:account -cne 'NT SERVICE\TicketboxPg' -or
    $script:sidType -cne 'unrestricted') {{
    throw 'fault injection did not preserve the prepared transition tuple'
}}
$transitionShapes = @(Get-TicketboxReleaseServiceIdentityShapes `
    -InstalledConfig $legacyConfig `
    -TargetConfig $currentConfig `
    -ServiceName TicketboxPg)
Assert-TicketboxServiceIdentityShape `
    -Name TicketboxPg `
    -AllowedShapes $transitionShapes | Out-Null
Set-TicketboxServiceIdentityContract `
    -Name TicketboxPg `
    -LogonAccount 'NT AUTHORITY\LocalService' `
    -SidType unrestricted
if (($script:calls -join ',') -cne
    'sid:unrestricted,account:NT AUTHORITY\LocalService' -or
    $script:account -cne 'NT AUTHORITY\LocalService' -or
    $script:sidType -cne 'unrestricted') {{
    throw 'retry did not converge the same prepared identity transition'
}}
"SERVICE_IDENTITY_TRANSITION_OK"
""",
        encoding="utf-8-sig",
    )
    _run_cross_engine(harness)
