from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGING / "windows_c07_superuser_recovery.ps1"
SECURITY_PRIMITIVES = PACKAGING / "windows_security_primitives.ps1"
SECURITY_PRIMITIVE_COMPONENTS = tuple(
    PACKAGING / "security_primitives" / name
    for name in (
        "byte_array.ps1",
        "token_privilege_native.ps1",
        "token_privilege.ps1",
        "descriptor_comparison.ps1",
        "descriptor_diagnostic.ps1",
        "file_security.ps1",
    )
)
SAFETY = PACKAGING / "windows_installation_safety.ps1"
DATABASE_SAFETY = PACKAGING / "windows_database_safety.ps1"
C07_DATABASE = PACKAGING / "windows_c07_database.ps1"
PG_RECOVERY_TOOLS = PACKAGING / "windows_pg_recovery_tools.ps1"

_TOKEN_PRIVILEGE_ORACLE = r"""
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct TicketboxTestLuid
{
    public uint LowPart;
    public int HighPart;
}

[StructLayout(LayoutKind.Sequential)]
public struct TicketboxTestLuidAndAttributes
{
    public TicketboxTestLuid Luid;
    public uint Attributes;
}

public static class TicketboxTokenPrivilegeOracle
{
    private const uint TokenQuery = 0x0008;
    private const int TokenPrivileges = 3;
    private const uint PrivilegeEnabled = 0x00000002;

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(
        IntPtr processHandle,
        uint desiredAccess,
        out IntPtr tokenHandle);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool LookupPrivilegeValue(
        string systemName,
        string name,
        out TicketboxTestLuid luid);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetTokenInformation(
        IntPtr tokenHandle,
        int tokenInformationClass,
        IntPtr tokenInformation,
        int tokenInformationLength,
        out int returnLength);

    public static bool IsEnabled(string privilegeName)
    {
        IntPtr tokenHandle;
        if (!OpenProcessToken(GetCurrentProcess(), TokenQuery, out tokenHandle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        try
        {
            TicketboxTestLuid expectedLuid;
            if (!LookupPrivilegeValue(null, privilegeName, out expectedLuid))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            int requiredLength;
            GetTokenInformation(
                tokenHandle,
                TokenPrivileges,
                IntPtr.Zero,
                0,
                out requiredLength);
            if (requiredLength <= 0)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            IntPtr buffer = Marshal.AllocHGlobal(requiredLength);
            try
            {
                if (!GetTokenInformation(
                    tokenHandle,
                    TokenPrivileges,
                    buffer,
                    requiredLength,
                    out requiredLength))
                {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                int count = Marshal.ReadInt32(buffer);
                int stride = Marshal.SizeOf(typeof(TicketboxTestLuidAndAttributes));
                for (int index = 0; index < count; index++)
                {
                    IntPtr itemPointer = IntPtr.Add(buffer, 4 + (index * stride));
                    TicketboxTestLuidAndAttributes item =
                        (TicketboxTestLuidAndAttributes)Marshal.PtrToStructure(
                            itemPointer,
                            typeof(TicketboxTestLuidAndAttributes));
                    if (item.Luid.LowPart == expectedLuid.LowPart &&
                        item.Luid.HighPart == expectedLuid.HighPart)
                    {
                        return (item.Attributes & PrivilegeEnabled) != 0;
                    }
                }
                return false;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }
        finally
        {
            CloseHandle(tokenHandle);
        }
    }
}
'@
function Test-IndependentTokenPrivilegeEnabled {
    param([Parameter(Mandatory = $true)][string]$PrivilegeName)
    return [TicketboxTokenPrivilegeOracle]::IsEnabled($PrivilegeName)
}
"""


def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_ps(engine: str, script: str, *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=timeout,
        check=False,
    )


def _function(source: str, name: str) -> str:
    start = source.index(f"function {name} {{")
    next_function = source.find("\nfunction ", start + 1)
    return source[start:] if next_function < 0 else source[start:next_function]


def _security_primitives_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8-sig") for path in (SECURITY_PRIMITIVES, *SECURITY_PRIMITIVE_COMPONENTS)
    )


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_superuser_capability_preserves_primary_and_cleanup_failures(
    engine: str,
) -> None:
    function = _function(
        SCRIPT.read_text(encoding="utf-8-sig"),
        "Throw-TicketboxC07SuperuserCapabilityFailure",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{function}
$primary = $null
$cleanup = $null
try {{
    $failure = [InvalidOperationException]::new('primary')
    $failure.Data['TicketboxC07FailureCode'] = 'primary_failed'
    throw $failure
}} catch {{ $primary = $_ }}
try {{ throw [IO.IOException]::new('cleanup') }}
catch {{ $cleanup = $_ }}
try {{
    Throw-TicketboxC07SuperuserCapabilityFailure $primary $cleanup
    throw 'combined failure was suppressed'
}} catch {{
    $caught = $_.Exception
}}
if ($caught -isnot [AggregateException] -or
    $caught.InnerExceptions.Count -ne 2 -or
    $caught.InnerExceptions[0].Message -cne 'primary' -or
    $caught.InnerExceptions[1].Message -cne 'cleanup' -or
    [string]$caught.Data['TicketboxC07FailureCode'] -cne 'primary_failed') {{
    throw 'primary/cleanup aggregate fidelity drifted'
}}
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_windows_security_primitives_are_c07_free_and_wired() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")
    primitives = _security_primitives_source()

    for path in (SECURITY_PRIMITIVES, *SECURITY_PRIMITIVE_COMPONENTS):
        component = path.read_text(encoding="utf-8-sig")
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert len(component.splitlines()) <= 300
        assert "c07" not in component.lower()
    entrypoint = SECURITY_PRIMITIVES.read_text(encoding="utf-8-sig")
    assert len(entrypoint.splitlines()) <= 30
    for component in SECURITY_PRIMITIVE_COMPONENTS:
        assert f'"{component.name}"' in entrypoint
    assert "windows_security_primitives.ps1" in source
    assert "TicketboxC07SecurityPrivilegeScope" not in source
    assert "Add-Type -TypeDefinition" not in source

    adapters = {
        "Enter-TicketboxC07SuperuserRecoverySecurityPrivilege": "Enter-TicketboxWindowsTokenPrivilege",
        "Get-TicketboxC07SuperuserRecoveryFileSecurityBytes": "Get-TicketboxWindowsFileSecurityBytes",
        "New-TicketboxC07SuperuserRecoveryCreationSecurity": "New-TicketboxWindowsFileCreationSecurity",
        "Get-TicketboxC07SuperuserRecoveryCreationSecuritySddl": "Get-TicketboxWindowsCreationSecuritySddl",
        "Set-TicketboxC07SuperuserRecoveryFileAuditSecurityBytes": "Set-TicketboxWindowsFileSecurityBytes",
    }
    adapter_source = ""
    dependency_contract = _function(
        source,
        "Assert-TicketboxC07SuperuserRecoveryDependencies",
    )
    for old_name, generic_name in adapters.items():
        body = _function(source, old_name)
        assert generic_name in body
        assert generic_name in dependency_contract
        adapter_source += body
    for forbidden_implementation in (
        "RawSecurityDescriptor",
        "FileSystemAclExtensions",
        ".GetAccessControl(",
        ".SetAccessControl(",
        "AdjustTokenPrivileges",
    ):
        assert forbidden_implementation not in adapter_source
    for retired_entry in (
        "Initialize-TicketboxC07SuperuserRecoverySecurityPrivilegeMethods",
        "Test-TicketboxC07SuperuserRecoverySecurityEquals",
        "Test-TicketboxC07SuperuserRecoveryRawAclEquals",
        "Get-TicketboxC07SuperuserRecoverySecurityDifferenceDiagnostic",
        "Test-TicketboxC07SuperuserRecoveryCreationSecurityEquals",
    ):
        assert retired_entry not in source
    generic_set = _function(
        primitives,
        "Set-TicketboxWindowsFileSecurityBytes",
    )
    generic_set_core = _function(
        primitives,
        "Set-TicketboxWindowsFileSecurityBytesCore",
    )
    auth_writer = _function(
        source,
        "Write-TicketboxC07SuperuserRecoveryAuthFile",
    )
    auth_state_reader = _function(
        source,
        "Get-TicketboxC07SuperuserRecoveryAuthState",
    )
    strict_candidate_functions = (
        "Assert-TicketboxC07SuperuserRecoveryReplacementCandidate",
        "Complete-TicketboxC07SuperuserRecoveryReplacementCandidate",
        "Assert-TicketboxC07SuperuserRecoveryBackupCandidate",
        "Assert-TicketboxC07SuperuserRecoveryDestinationCandidate",
    )
    token_scope = _function(
        primitives,
        "Initialize-TicketboxWindowsTokenPrivilegeMethods",
    )
    for official_privilege_contract in (
        "ErrorNotAllAssigned = 1300",
        "out scope.previousState",
        "ref previousState",
        "restoreError == ErrorNotAllAssigned",
        "CloseHandle(tokenHandle)",
    ):
        assert official_privilege_contract in token_scope
    assert "Invoke-TicketboxWindowsTokenPrivilegeScopes" in generic_set
    assert '"SeSecurityPrivilege"' in generic_set
    assert '"SeRestorePrivilege"' in generic_set
    assert "Get-TicketboxWindowsFileSecurityBytesCore" in generic_set
    assert "Set-TicketboxWindowsFileSecurityBytesCore" in generic_set
    assert "-Sections $Context.Sections" in generic_set
    assert (
        "$security.SetSecurityDescriptorBinaryForm($SecurityBytes, $Sections)"
        in generic_set_core
    )
    audit_adapter = _function(
        source,
        "Set-TicketboxC07SuperuserRecoveryFileAuditSecurityBytes",
    )
    assert "AccessControlSections]::Audit" in audit_adapter
    assert '-PrivilegeNames @("SeSecurityPrivilege")' in audit_adapter
    assert '"SeRestorePrivilege"' not in audit_adapter
    assert (
        "Enter-TicketboxC07SuperuserRecoverySecurityPrivilege `\n"
        '        -PrivilegeName "SeSecurityPrivilege"' in auth_writer
    )
    assert "-AllowWindowsReplacementDaclProjection" in auth_state_reader
    assert "-AllowWindowsReplacementDaclProjection" in auth_writer
    for strict_candidate_function in strict_candidate_functions:
        assert "-AllowWindowsReplacementDaclProjection" not in _function(
            source,
            strict_candidate_function,
        )

    production_sources = {
        path: path.read_text(encoding="utf-8-sig") for path in PACKAGING.rglob("*.ps1") if "tests" not in path.parts
    }
    assert [path for path, candidate in production_sources.items() if "AdjustTokenPrivileges" in candidate] == [
        PACKAGING / "security_primitives" / "token_privilege_native.ps1"
    ]
    assert [
        path
        for path, candidate in production_sources.items()
        if "function Test-TicketboxWindowsByteArrayEquals" in candidate
    ] == [PACKAGING / "security_primitives" / "byte_array.ps1"]
    assert all("TicketboxRestorePrivilegeScope" not in candidate for candidate in production_sources.values())


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_windows_token_privilege_scope_restores_on_success_and_failure(
    engine: str,
) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. {_ps_literal(SECURITY_PRIMITIVES)}
$script:disposeCount = 0
function New-TestPrivilegeScope {{
    $scope = New-Object psobject
    $scope | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{
        $script:disposeCount++
    }}
    return $scope
}}
$value = Invoke-TicketboxWindowsTokenPrivilegeScope `
    -PrivilegeName 'TestPrivilege' `
    -PrivilegeScopeFactory {{ New-TestPrivilegeScope }} `
    -Action {{ return 'success-value' }}
if ($value -cne 'success-value' -or $script:disposeCount -ne 1) {{
    throw 'success path did not restore the privilege scope exactly once'
}}
$caught = $false
try {{
    Invoke-TicketboxWindowsTokenPrivilegeScope `
        -PrivilegeName 'TestPrivilege' `
        -PrivilegeScopeFactory {{ New-TestPrivilegeScope }} `
        -Action {{ throw 'injected action failure' }} | Out-Null
}}
catch {{
    if (-not $_.Exception.GetBaseException().Message.Contains(
        'injected action failure'
    )) {{
        throw
    }}
    $caught = $true
}}
if (-not $caught -or $script:disposeCount -ne 2) {{
    throw 'failure path did not restore the privilege scope exactly once'
}}
$factoryRejected = $false
try {{
    Invoke-TicketboxWindowsTokenPrivilegeScope `
        -PrivilegeName 'TestPrivilege' `
        -PrivilegeScopeFactory {{
            New-TestPrivilegeScope
            'injected factory noise'
        }} `
        -Action {{ throw 'factory output validation failed open' }} | Out-Null
}}
catch {{
    if (-not $_.Exception.GetBaseException().Message.Contains(
        '必须返回一个 scope'
    )) {{
        throw
    }}
    $factoryRejected = $true
}}
if (-not $factoryRejected -or $script:disposeCount -ne 3) {{
    throw 'invalid factory output leaked an acquired privilege scope'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_native_token_privilege_restores_exact_process_state(engine: str) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. {_ps_literal(SECURITY_PRIMITIVES)}
{_TOKEN_PRIVILEGE_ORACLE}
$candidate = $null
foreach ($privilegeName in @(
    'SeIncreaseWorkingSetPrivilege',
    'SeTimeZonePrivilege',
    'SeShutdownPrivilege',
    'SeBackupPrivilege',
    'SeRestorePrivilege',
    'SeSecurityPrivilege'
)) {{
    if (Test-IndependentTokenPrivilegeEnabled -PrivilegeName $privilegeName) {{
        continue
    }}
    try {{
        $scope = Enter-TicketboxWindowsTokenPrivilege -PrivilegeName $privilegeName
        try {{
            if (-not (Test-IndependentTokenPrivilegeEnabled `
                -PrivilegeName $privilegeName)) {{
                throw 'candidate privilege was not enabled inside scope'
            }}
        }}
        finally {{
            $scope.Dispose()
        }}
        if (Test-IndependentTokenPrivilegeEnabled -PrivilegeName $privilegeName) {{
            throw 'candidate privilege was not restored after capability probe'
        }}
        $candidate = $privilegeName
        break
    }}
    catch {{
        $baseException = $_.Exception.GetBaseException()
        if (
            $baseException -is [System.ComponentModel.Win32Exception] -and
            $baseException.NativeErrorCode -eq 1300
        ) {{
            continue
        }}
        throw
    }}
}}
if ($null -eq $candidate) {{
    if ($env:GITHUB_ACTIONS -ceq 'true') {{
        throw 'Windows CI has no assigned disabled token privilege candidate'
    }}
    'SKIP_CAPABILITY:no assigned disabled token privilege'
    exit 0
}}
$insideSuccess = Invoke-TicketboxWindowsTokenPrivilegeScope `
    -PrivilegeName $candidate `
    -Action {{ Test-IndependentTokenPrivilegeEnabled -PrivilegeName $candidate }}
if (-not $insideSuccess -or
    (Test-IndependentTokenPrivilegeEnabled -PrivilegeName $candidate)) {{
    throw 'success path did not restore exact pre-scope token state'
}}
$caught = $false
try {{
    Invoke-TicketboxWindowsTokenPrivilegeScope `
        -PrivilegeName $candidate `
        -Action {{
            if (-not (Test-IndependentTokenPrivilegeEnabled `
                -PrivilegeName $candidate)) {{
                throw 'failure path privilege was not enabled inside scope'
            }}
            throw 'injected native action failure'
        }} | Out-Null
}}
catch {{
    if (-not $_.Exception.GetBaseException().Message.Contains(
        'injected native action failure'
    )) {{
        throw
    }}
    $caught = $true
}}
if (-not $caught -or
    (Test-IndependentTokenPrivilegeEnabled -PrivilegeName $candidate)) {{
    throw 'failure path did not restore exact pre-scope token state'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    last_line = result.stdout.strip().splitlines()[-1]
    if last_line.startswith("SKIP_CAPABILITY:"):
        pytest.skip(last_line)
    assert last_line == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_windows_security_apply_restores_privilege_before_callback_and_on_failure(
    engine: str,
    tmp_path: Path,
) -> None:
    target = tmp_path / f"{Path(engine).stem}-generic-security-target.txt"
    missing = tmp_path / f"{Path(engine).stem}-generic-security-missing.txt"
    drift = tmp_path / f"{Path(engine).stem}-generic-security-drift.txt"
    script = f"""
$ErrorActionPreference = 'Stop'
. {_ps_literal(SECURITY_PRIMITIVES)}
[IO.File]::WriteAllText({_ps_literal(target)}, 'payload')
$item = Get-Item -LiteralPath {_ps_literal(target)} -Force
$sections =
    [Security.AccessControl.AccessControlSections]::Access -bor
    [Security.AccessControl.AccessControlSections]::Owner -bor
    [Security.AccessControl.AccessControlSections]::Group
$security = if ($PSVersionTable.PSEdition -eq 'Core') {{
    [System.IO.FileSystemAclExtensions]::GetAccessControl($item, $sections)
}}
else {{
    $item.GetAccessControl($sections)
}}
$script:expectedSecurity = $security.GetSecurityDescriptorBinaryForm()
$driftedDescriptor = New-Object `
    Security.AccessControl.RawSecurityDescriptor($script:expectedSecurity, 0)
$driftedGroup = New-Object Security.Principal.SecurityIdentifier(
    'S-1-5-32-544'
)
if ($driftedDescriptor.Group.Equals($driftedGroup)) {{
    $driftedGroup = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
}}
$driftedDescriptor.Group = $driftedGroup
$script:driftedSecurity = New-Object byte[] $driftedDescriptor.BinaryLength
$driftedDescriptor.GetBinaryForm($script:driftedSecurity, 0)
$script:disposeCount = 0
$script:callbackCount = 0
function New-TestPrivilegeScope {{
    $scope = New-Object psobject
    $scope | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{
        $script:disposeCount++
    }}
    return $scope
}}
function Get-TicketboxWindowsFileSecurityBytesCore {{
    param($Path)
    if ($Path -ceq {_ps_literal(drift)}) {{
        return $script:driftedSecurity
    }}
    return $script:expectedSecurity
}}
function Set-TicketboxWindowsFileSecurityBytesCore {{
    param($Path, $SecurityBytes, $Label, $Sections)
    if ($Sections -ne [Security.AccessControl.AccessControlSections]::All) {{
        throw 'default security apply did not request every section'
    }}
    if ($Path -ceq {_ps_literal(missing)}) {{
        throw "$Label injected apply failure"
    }}
}}
Set-TicketboxWindowsFileSecurityBytes `
    -Path {_ps_literal(target)} `
    -SecurityBytes $script:expectedSecurity `
    -Label 'generic security target' `
    -PrivilegeScopeFactory {{ New-TestPrivilegeScope }} `
    -AfterVerified {{
        if ($script:disposeCount -ne 2) {{
            throw 'verified callback ran before privilege restoration'
        }}
        $script:callbackCount++
    }}
if ($script:disposeCount -ne 2 -or $script:callbackCount -ne 1) {{
    throw 'success path scope/callback count mismatch'
}}
$caught = $false
try {{
    Set-TicketboxWindowsFileSecurityBytes `
        -Path {_ps_literal(missing)} `
        -SecurityBytes $script:expectedSecurity `
        -Label 'missing security target' `
        -PrivilegeScopeFactory {{ New-TestPrivilegeScope }} `
        -AfterVerified {{ $script:callbackCount++ }}
}}
catch {{
    if (-not $_.Exception.GetBaseException().Message.Contains(
        'missing security target'
    )) {{
        throw
    }}
    $caught = $true
}}
if (
    -not $caught -or
    $script:disposeCount -ne 4 -or
    $script:callbackCount -ne 1
) {{
    throw 'failure path did not restore before suppressing callback'
}}
$driftRejected = $false
try {{
    Set-TicketboxWindowsFileSecurityBytes `
        -Path {_ps_literal(drift)} `
        -SecurityBytes $script:expectedSecurity `
        -Label 'drifted security target' `
        -PrivilegeScopeFactory {{ New-TestPrivilegeScope }} `
        -AfterVerified {{ $script:callbackCount++ }}
}}
catch {{
    if (-not $_.Exception.GetBaseException().Message.Contains(
        '复读不一致'
    )) {{
        throw
    }}
    $driftRejected = $true
}}
if (
    -not $driftRejected -or
    $script:disposeCount -ne 6 -or
    $script:callbackCount -ne 1
) {{
    throw 'descriptor readback drift did not fail before verified callback'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_windows_security_apply_can_update_only_the_audit_section(
    engine: str,
    tmp_path: Path,
) -> None:
    target = tmp_path / f"{Path(engine).stem}-generic-audit-target.txt"
    script = f"""
$ErrorActionPreference = 'Stop'
. {_ps_literal(SECURITY_PRIMITIVES)}
[IO.File]::WriteAllText({_ps_literal(target)}, 'payload')
$item = Get-Item -LiteralPath {_ps_literal(target)} -Force
$sections =
    [Security.AccessControl.AccessControlSections]::Access -bor
    [Security.AccessControl.AccessControlSections]::Owner -bor
    [Security.AccessControl.AccessControlSections]::Group
$security = if ($PSVersionTable.PSEdition -eq 'Core') {{
    [System.IO.FileSystemAclExtensions]::GetAccessControl($item, $sections)
}}
else {{ $item.GetAccessControl($sections) }}
$script:expectedSecurity = $security.GetSecurityDescriptorBinaryForm()
$script:observedSections = $null
$script:disposeCount = 0
$script:callbackCount = 0
function New-TestPrivilegeScope {{
    $scope = New-Object psobject
    $scope | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{
        $script:disposeCount++
    }}
    return $scope
}}
function Set-TicketboxWindowsFileSecurityBytesCore {{
    param($Path, $SecurityBytes, $Label, $Sections)
    $script:observedSections = $Sections
}}
function Get-TicketboxWindowsFileSecurityBytesCore {{
    param($Path)
    return $script:expectedSecurity
}}
Set-TicketboxWindowsFileSecurityBytes `
    -Path {_ps_literal(target)} `
    -SecurityBytes $script:expectedSecurity `
    -Label 'generic audit target' `
    -Sections ([Security.AccessControl.AccessControlSections]::Audit) `
    -PrivilegeNames @('SeSecurityPrivilege') `
    -PrivilegeScopeFactory {{ New-TestPrivilegeScope }} `
    -AfterVerified {{
        if ($script:disposeCount -ne 1) {{
            throw 'audit callback ran before privilege restoration'
        }}
        $script:callbackCount++
    }}
if (
    $script:observedSections -ne
        [Security.AccessControl.AccessControlSections]::Audit -or
    $script:disposeCount -ne 1 -or
    $script:callbackCount -ne 1
) {{
    throw 'audit-only apply did not retain its section/callback contract'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


def test_source_contract_is_narrow_sspi_and_secret_safe() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")
    security_primitives = _security_primitives_source()
    host_operations = PG_RECOVERY_TOOLS.read_text(encoding="utf-8-sig")
    safety = SAFETY.read_text(encoding="utf-8-sig")
    publish = _function(source, "Publish-TicketboxC07SuperuserRecoverySspi")
    restore = _function(source, "Restore-TicketboxC07SuperuserRecoveryAuthFiles")
    rotate = _function(
        source,
        "Invoke-TicketboxC07SuperuserRecoveryRotateCredential",
    )
    retire = _function(
        source,
        "Invoke-TicketboxC07SuperuserRecoveryClearCredential",
    )
    remove = _function(
        source,
        "Remove-TicketboxC07CompletedSuperuserRecoveryArtifact",
    )
    acquire = _function(
        source,
        "Acquire-TicketboxC07SuperuserCapability",
    )
    renew = _function(source, "Renew-TicketboxC07SuperuserCapability")
    revoke = _function(source, "Revoke-TicketboxC07SuperuserCapability")
    validate_capability = _function(
        source,
        "Assert-TicketboxC07SuperuserCapability",
    )
    host = _function(source, "Resolve-TicketboxC07SuperuserRecoveryHost")
    reload = _function(source, "Invoke-TicketboxC07SuperuserRecoveryReload")
    database_identity = _function(
        source,
        "Assert-TicketboxC07SuperuserRecoveryDatabaseIdentityRow",
    )
    security_reader = _function(
        security_primitives,
        "Get-TicketboxWindowsFileSecurityBytesCore",
    )
    security_diagnostic = _function(
        security_primitives,
        "Get-TicketboxWindowsSecurityDescriptorDifferenceDiagnostic",
    )
    security_writer = _function(
        security_primitives,
        "Set-TicketboxWindowsFileSecurityBytes",
    )
    security_privilege = _function(
        source,
        "Enter-TicketboxC07SuperuserRecoverySecurityPrivilege",
    )
    auth_writer = _function(
        source,
        "Write-TicketboxC07SuperuserRecoveryAuthFile",
    )

    assert " trust " not in source.lower()
    assert "PGPASSWORD" not in source
    database_url = _function(
        source,
        "New-TicketboxC07SuperuserRecoveryDatabaseUrl",
    )
    psql = _function(
        source,
        "Invoke-TicketboxC07SuperuserRecoveryPsql",
    )
    assert "postgres@localhost:" in database_url
    assert "?hostaddr=127.0.0.1&require_auth=sspi" in database_url
    assert "postgres@127.0.0.1:" in database_url
    assert "?require_auth=scram-sha-256" in database_url
    assert '[ValidateSet("sspi", "scram-sha-256")]' in database_url
    assert '[ValidateSet("sspi", "scram-sha-256")]' in psql
    assert 'host "postgres" "postgres" 127.0.0.1/32 sspi ' in source
    assert "include_realm=1" in source
    assert "compat_realm=1" in source
    assert "upn_username=0" in source
    assert "map=$($Artifact.map_name)" in source
    assert "krb_realm=" not in source
    assert "127.0.0.1:$($Artifact.port):postgres:postgres:" in source
    assert "$env:PGPASSFILE" in host_operations
    assert "ConvertTo-TicketboxC07ScramVerifier" in source
    assert "StandardInputText" in host_operations
    assert "ANSICodePage" in source
    assert "[Text.EncoderFallback]::ExceptionFallback" in source
    assert "Invoke-TicketboxPostgresqlHostCredentialRotation" in rotate
    assert "ALTER ROLE postgres WITH LOGIN PASSWORD" not in rotate
    assert "ALTER ROLE postgres WITH LOGIN PASSWORD" in host_operations
    assert "ALTER ROLE postgres WITH LOGIN PASSWORD NULL" in retire
    assert "role.rolcanlogin::text" in retire
    assert "(role.rolpassword IS NULL)::text" in retire

    assert publish.index("publish temporary pg_ident.conf") < publish.index(
        "Invoke-TicketboxC07SuperuserRecoveryReload"
    )
    assert publish.index("Invoke-TicketboxC07SuperuserRecoveryReload") < publish.index("publish temporary pg_hba.conf")
    assert restore.index("restore pg_hba.conf") < restore.index("restore pg_ident.conf")
    assert 'stage -cne "completed"' in remove
    assert "Remove-TicketboxProtectedUtf8Artifact" in remove
    assert "Invoke-TicketboxC07RecoveredSuperuserAction" not in source
    assert "[scriptblock]" not in acquire + renew + revoke
    assert "Assert-TicketboxLifecycleOperationLease" in validate_capability
    assert 'Schema = "ticketbox-postgresql-superuser-capability-v1"' in acquire
    assert "Assert-TicketboxC07SuperuserCapability" in renew
    assert "$Capability.Closed = $true" in revoke
    assert "$Capability.Secret.Dispose()" in revoke
    assert "FilesystemPgData" in host
    assert "FilesystemPgData" in reload
    assert "Test-TicketboxC07SuperuserRecoveryDatabaseDataPath" in database_identity
    assert "SeSecurityPrivilege" in security_privilege
    assert "AdjustTokenPrivileges" in security_primitives
    assert "AccessControlSections]::All" in security_reader
    assert "control_flags_left=0x" in security_diagnostic
    assert "control_flags_right=0x" in security_diagnostic
    assert "control_flags_xor=0x" in security_diagnostic
    assert "dacl_binary_equal=" in security_diagnostic
    assert "sacl_binary_equal=" in security_diagnostic
    assert "GetSddlForm" not in security_diagnostic
    assert ".Owner.Value" not in security_diagnostic
    assert ".Group.Value" not in security_diagnostic
    assert "Get-TicketboxWindowsSecurityDescriptorDifferenceDiagnostic" in security_writer
    assert "Replace-TicketboxFileDurablePreservingMetadata" in auth_writer
    assert "-Backup $backupPath" in auth_writer
    assert "PreviousSha256" in auth_writer
    assert ".ticketbox-c07-replacement" in auth_writer
    assert ".ticketbox-c07-replacement-staging" in auth_writer
    assert ".ticketbox-c07-backup" in auth_writer
    assert "ErrorAction SilentlyContinue" not in auth_writer
    assert "ReplaceFileWriteThrough" not in safety
    assert "backupFileName" in safety
    assert "NativeErrorCode" in safety
    assert auth_writer.index("DestinationCandidate") < auth_writer.index(
        "Replace-TicketboxFileDurablePreservingMetadata"
    )
    assert auth_writer.index("Replace-TicketboxFileDurablePreservingMetadata") < (
        auth_writer.index("destination after ReplaceFileW")
    )


_STUBS = r"""
function Assert-NoTicketboxAncestorReparsePoints { param([string]$Path) }
function Assert-TicketboxProtectedDirectoryAcl { param($Path, $FullControlAccounts, $OwnerAccount) }
function ConvertTo-TicketboxCanonicalPath { param([string]$Path); return [IO.Path]::GetFullPath($Path) }
function Test-TicketboxPathEquals {
    param([string]$Left, [string]$Right)
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left),
        [IO.Path]::GetFullPath($Right),
        [StringComparison]::OrdinalIgnoreCase
    )
}
function Get-TicketboxPathEntryKindNoFollow {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return 'File' }
    if (Test-Path -LiteralPath $Path -PathType Container) { return 'Directory' }
    return 'Missing'
}
function Test-TicketboxWindowsByteArrayEquals {
    param([byte[]]$Left, [byte[]]$Right)
    if ($Left.Length -ne $Right.Length) { return $false }
    for ($i = 0; $i -lt $Left.Length; $i++) {
        if ($Left[$i] -ne $Right[$i]) { return $false }
    }
    return $true
}
function Write-TicketboxProtectedUtf8FileDurable {
    param($Path, $Text, $FullControlAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false, $true)))
}
function Read-TicketboxProtectedUtf8Artifact {
    param($Path, $FullControlAccounts, $OwnerAccount, $MaximumBytes)
    $bytes = [IO.File]::ReadAllBytes($Path)
    return [pscustomobject]@{
        Text = (New-Object Text.UTF8Encoding($false, $true)).GetString($bytes)
        Bytes = $bytes
    }
}
function Remove-TicketboxProtectedUtf8Artifact {
    param($Path, $FullControlAccounts, $OwnerAccount)
    Remove-Item -LiteralPath $Path -Force
}
function ConvertTo-TicketboxC07ScramVerifier { param($Password, $Salt); return 'unused' }
function Invoke-TicketboxBoundedNativeProcess { throw 'unused' }
function Replace-TicketboxFileDurablePreservingMetadata { throw 'unused' }
function New-TicketboxProtectedFileStream { throw 'unused' }
function Sync-TicketboxFileDurable { param($Path) }
"""


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_managed_runtime_binding_uses_only_physical_pgdata_for_native_filesystem(
    engine: str,
    tmp_path: Path,
) -> None:
    install_bin = tmp_path / "install" / "pg" / "bin"
    physical_pgdata = tmp_path / "data" / "pgdata"
    runtime_pgdata = tmp_path / "runtime" / "data-root" / "pgdata"
    third_pgdata = tmp_path / "foreign" / "pgdata"
    for directory in (install_bin, physical_pgdata, runtime_pgdata, third_pgdata):
        directory.mkdir(parents=True)
    for path in (
        install_bin / "pg_ctl.exe",
        install_bin / "psql.exe",
        physical_pgdata / "postgresql.conf",
        physical_pgdata / "PG_VERSION",
        physical_pgdata / "pg_hba.conf",
        physical_pgdata / "pg_ident.conf",
    ):
        path.write_text("managed\n", encoding="utf-8")

    script = f"""
{_STUBS}
. {_ps_literal(SCRIPT)}
$script:reparseChecks = [Collections.Generic.List[string]]::new()
$script:authPaths = [Collections.Generic.List[string]]::new()
$script:clusterPgData = ''
$script:reloadArguments = @()
function Assert-NoTicketboxAncestorReparsePoints {{
    param([string]$Path)
    $script:reparseChecks.Add([IO.Path]::GetFullPath($Path))
}}
function Get-TicketboxC07SuperuserRecoveryAuthFile {{
    param([string]$Path, [string]$Label)
    $script:authPaths.Add([IO.Path]::GetFullPath($Path))
    return [pscustomobject]@{{
        Path = [IO.Path]::GetFullPath($Path)
        Bytes = [byte[]](1)
        Sha256 = ('A' * 64)
        SecurityBytes = [byte[]](2)
    }}
}}
function Get-TicketboxC07SuperuserRecoveryClusterSystemIdentifier {{
    param([object]$HostAuthority, [string]$FilesystemPgData)
    $script:clusterPgData = [IO.Path]::GetFullPath($FilesystemPgData)
    return '7123456789012345678'
}}
$runtimeAuthority = [pscustomobject]@{{
    Schema = 'ticketbox-c07-host-db-authority-v1'
    PgCtlPath = {_ps_literal(install_bin / "pg_ctl.exe")}
    PsqlPath = {_ps_literal(install_bin / "psql.exe")}
    PgData = {_ps_literal(runtime_pgdata)}
    PhysicalPgData = {_ps_literal(physical_pgdata)}
    Port = 5544
    UsesRuntimeBinding = $true
    DataVolumeIdentity = 'volume-A'
}}
$runtimeHostContext = Resolve-TicketboxC07SuperuserRecoveryHost $runtimeAuthority
if (
    -not $runtimeHostContext.UsesRuntimeBinding -or
    -not (Test-TicketboxPathEquals `
        $runtimeHostContext.PgData {_ps_literal(runtime_pgdata)}) -or
    -not (Test-TicketboxPathEquals `
        $runtimeHostContext.FilesystemPgData {_ps_literal(physical_pgdata)}) -or
    -not (Test-TicketboxPathEquals `
        $script:clusterPgData {_ps_literal(physical_pgdata)}) -or
    $script:authPaths.Count -ne 2 -or
    ($script:authPaths | Where-Object {{
        -not (Test-TicketboxPathEquals `
            (Split-Path -Parent $_) {_ps_literal(physical_pgdata)})
    }}) -or
    ($script:reparseChecks | Where-Object {{
        Test-TicketboxPathEquals $_ {_ps_literal(runtime_pgdata)}
    }})
) {{
    throw 'managed runtime binding escaped the physical filesystem authority'
}}
function Invoke-TicketboxC07SuperuserRecoveryNative {{
    param($FilePath, $Arguments, $TimeoutMilliseconds, $Label)
    $script:reloadArguments = @($Arguments)
    return [pscustomobject]@{{ ExitCode = 0 }}
}}
Invoke-TicketboxC07SuperuserRecoveryReload -HostContext $runtimeHostContext
if (
    $script:reloadArguments.Count -ne 4 -or
    $script:reloadArguments[0] -cne 'reload' -or
    $script:reloadArguments[1] -cne '-D' -or
    -not (Test-TicketboxPathEquals `
        $script:reloadArguments[2] {_ps_literal(physical_pgdata)}) -or
    $script:reloadArguments[3] -cne '-s'
) {{ throw 'pg_ctl reload did not use exact physical PGDATA' }}
$baseFields = @(
    'postgres', 'postgres', '7123456789012345678', '', '5544'
)
foreach ($acceptedPath in @(
    {_ps_literal(runtime_pgdata)}, {_ps_literal(physical_pgdata)}
)) {{
    $fields = @($baseFields)
    $fields[3] = $acceptedPath
    Assert-TicketboxC07SuperuserRecoveryDatabaseIdentityRow `
        -Fields $fields -HostContext $runtimeHostContext -Label 'runtime identity'
}}
$rejected = $false
try {{
    $fields = @($baseFields)
    $fields[3] = {_ps_literal(third_pgdata)}
    Assert-TicketboxC07SuperuserRecoveryDatabaseIdentityRow `
        -Fields $fields -HostContext $runtimeHostContext -Label 'foreign identity'
}}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'third PGDATA identity was accepted' }}
$missingPhysical = $runtimeAuthority.PSObject.Copy()
$missingPhysical.PhysicalPgData = ''
$rejected = $false
try {{ Resolve-TicketboxC07SuperuserRecoveryHost $missingPhysical | Out-Null }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'runtime authority without physical PGDATA was accepted' }}
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_replacefile_preserves_real_descriptor_while_movefile_mutation_does_not(
    engine: str,
    tmp_path: Path,
) -> None:
    target = tmp_path / f"{Path(engine).stem}-descriptor-target.conf"
    replacement = tmp_path / f"{Path(engine).stem}-descriptor-replacement.tmp"
    backup = tmp_path / f"{Path(engine).stem}-descriptor-backup.tmp"
    mutation = tmp_path / f"{Path(engine).stem}-descriptor-mutation.tmp"
    script = f"""
$ErrorActionPreference = 'Stop'
. {_ps_literal(SAFETY)}
. {_ps_literal(SCRIPT)}
$identitySid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allSections = [Security.AccessControl.AccessControlSections]::All
$semanticSecurity = New-Object Security.AccessControl.FileSecurity
$semanticSecurity.SetSecurityDescriptorSddlForm(
    ("O:{{0}}G:{{0}}D:P(A;;FA;;;{{0}})S:P(AU;SA;WD;;;{{0}})" -f $identitySid),
    $allSections
)
$semanticSecurityBytes = $semanticSecurity.GetSecurityDescriptorBinaryForm()
$semanticRawSecurity = New-Object `
    Security.AccessControl.RawSecurityDescriptor($semanticSecurityBytes,0)
$resourceManagerDerivedSecurity = New-Object `
    Security.AccessControl.RawSecurityDescriptor($semanticSecurityBytes,0)
$resourceManagerDerivedSecurity.SetFlags(
    $resourceManagerDerivedSecurity.ControlFlags -bor
        [Security.AccessControl.ControlFlags]::OwnerDefaulted -bor
        [Security.AccessControl.ControlFlags]::GroupDefaulted -bor
        [Security.AccessControl.ControlFlags]::DiscretionaryAclDefaulted -bor
        [Security.AccessControl.ControlFlags]::SystemAclDefaulted -bor
        [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInheritRequired -bor
        [Security.AccessControl.ControlFlags]::SystemAclAutoInheritRequired -bor
        [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited -bor
        [Security.AccessControl.ControlFlags]::SystemAclAutoInherited
)
$resourceManagerDerivedSecurityBytes =
    New-Object byte[] $resourceManagerDerivedSecurity.BinaryLength
$resourceManagerDerivedSecurity.GetBinaryForm(
    $resourceManagerDerivedSecurityBytes,
    0
)
$providerMetadataDiagnostic =
    Get-TicketboxWindowsSecurityDescriptorDifferenceDiagnostic `
        -Left $semanticSecurityBytes `
        -Right $resourceManagerDerivedSecurityBytes
$providerMetadataExpectedFields = @(
    ("control_flags_left=0x{{0:X4}}" -f (
        [int]$semanticRawSecurity.ControlFlags -band 0xFFFF
    )),
    ("control_flags_right=0x{{0:X4}}" -f (
        [int]$resourceManagerDerivedSecurity.ControlFlags -band 0xFFFF
    )),
    ("control_flags_xor=0x{{0:X4}}" -f (
        ([int]$semanticRawSecurity.ControlFlags -bxor
            [int]$resourceManagerDerivedSecurity.ControlFlags) -band 0xFFFF
    )),
    'owner_equal=true',
    'group_equal=true',
    'dacl_component_equal=false',
    'dacl_binary_equal=true',
    'sacl_component_equal=false',
    'sacl_binary_equal=true',
    'rm_control_equal=true',
    'revision_equal=true'
)
foreach ($expectedField in $providerMetadataExpectedFields) {{
    if (-not $providerMetadataDiagnostic.Contains($expectedField)) {{
        throw "security diagnostic missing $expectedField"
    }}
}}
if ($providerMetadataDiagnostic.Contains($identitySid) -or
    $providerMetadataDiagnostic.Contains('S-1-')) {{
    throw 'security diagnostic leaked descriptor identity content'
}}
if (-not (Test-TicketboxWindowsSecurityDescriptorEquals `
    -Left $semanticSecurityBytes `
    -Right $resourceManagerDerivedSecurityBytes)) {{
    throw 'descriptor resource-manager provenance changed security authority'
}}
$inheritanceSecurity = New-Object Security.AccessControl.FileSecurity
$inheritanceSecurity.SetSecurityDescriptorSddlForm(
    ("O:{{0}}G:{{0}}D:(A;;FA;;;{{0}})(A;;FR;;;BA)S:P(AU;SA;WD;;;{{0}})" -f $identitySid),
    $allSections
)
$inheritanceSecurityBytes = $inheritanceSecurity.GetSecurityDescriptorBinaryForm()
$autoInheritedSecurity = New-Object `
    Security.AccessControl.RawSecurityDescriptor($inheritanceSecurityBytes,0)
$reorderedAcl = New-Object Security.AccessControl.RawAcl(
    $autoInheritedSecurity.DiscretionaryAcl.Revision,
    ($autoInheritedSecurity.DiscretionaryAcl.Count + 1)
)
for (
    $aceIndex = $autoInheritedSecurity.DiscretionaryAcl.Count - 1;
    $aceIndex -ge 0;
    $aceIndex--
) {{
    $ace = $autoInheritedSecurity.DiscretionaryAcl[$aceIndex]
    $ace.AceFlags = [Security.AccessControl.AceFlags](
        [int]$ace.AceFlags -bor
            [int][Security.AccessControl.AceFlags]::Inherited
    )
    $reorderedAcl.InsertAce($reorderedAcl.Count,$ace)
    # Automatic inheritance may materialize an equivalent qualified ACE twice.
    if ($aceIndex -eq 0) {{
        $reorderedAcl.InsertAce($reorderedAcl.Count,$ace)
    }}
}}
$autoInheritedSecurity.DiscretionaryAcl = $reorderedAcl
$autoInheritedSecurity.SetFlags(
    $autoInheritedSecurity.ControlFlags -bor
        [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited
)
$autoInheritedSecurityBytes =
    New-Object byte[] $autoInheritedSecurity.BinaryLength
$autoInheritedSecurity.GetBinaryForm($autoInheritedSecurityBytes,0)
if (Test-TicketboxWindowsSecurityDescriptorEquals `
    -Left $inheritanceSecurityBytes `
    -Right $autoInheritedSecurityBytes) {{
    throw 'descriptor comparison treated explicit and inherited ACEs as one authority'
}}
if (-not (Test-TicketboxWindowsSecurityDescriptorEquals `
    -Left $autoInheritedSecurityBytes `
    -Right $inheritanceSecurityBytes `
    -AllowWindowsReplacementDaclProjection)) {{
    throw 'ReplaceFileW projection did not accept exact auto-inherited DACL semantics'
}}
if (Test-TicketboxWindowsSecurityDescriptorEquals `
    -Left $inheritanceSecurityBytes `
    -Right $autoInheritedSecurityBytes `
    -AllowWindowsReplacementDaclProjection) {{
    throw 'ReplaceFileW projection accepted the inverse provenance transition'
}}
$inheritedCandidateRejected = $false
try {{
    Assert-TicketboxC07SuperuserRecoveryReplacementCandidate `
        -Candidate ([pscustomobject]@{{
            Sha256 = 'A' * 64
            SecurityBytes = $autoInheritedSecurityBytes
        }}) `
        -ExpectedSha256 ('A' * 64) `
        -ExpectedSecurityBytes $inheritanceSecurityBytes `
        -Label 'inherited creation security'
}}
catch {{
    $inheritedCandidateRejected = $true
}}
if (-not $inheritedCandidateRejected) {{
    throw 'replacement candidate accepted changed ACE inheritance provenance'
}}
foreach ($protectionFlag in @(
    [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected,
    [Security.AccessControl.ControlFlags]::SystemAclProtected
)) {{
    $unprotectedSecurity = New-Object `
        Security.AccessControl.RawSecurityDescriptor($semanticSecurityBytes,0)
    $unprotectedSecurity.SetFlags(
        [Security.AccessControl.ControlFlags](
            [int]$unprotectedSecurity.ControlFlags -band
                (-bnot [int]$protectionFlag)
        )
    )
    $unprotectedSecurityBytes =
        New-Object byte[] $unprotectedSecurity.BinaryLength
    $unprotectedSecurity.GetBinaryForm($unprotectedSecurityBytes,0)
    if (Test-TicketboxWindowsSecurityDescriptorEquals `
        -Left $semanticSecurityBytes `
        -Right $unprotectedSecurityBytes) {{
        throw 'descriptor comparison ignored ACL protection authority'
    }}
}}
$mutatedSecuritySddls = @(
    ("O:S-1-5-32-544G:{{0}}D:P(A;;FA;;;{{0}})S:P(AU;SA;WD;;;{{0}})" -f $identitySid),
    ("O:{{0}}G:BAD:P(A;;FA;;;{{0}})S:P(AU;SA;WD;;;{{0}})" -f $identitySid),
    ("O:{{0}}G:{{0}}D:P(A;;FR;;;{{0}})S:P(AU;SA;WD;;;{{0}})" -f $identitySid),
    ("O:{{0}}G:{{0}}D:P(A;;FA;;;{{0}})S:P(AU;FA;WD;;;{{0}})" -f $identitySid)
)
$expectedMutationDiagnostics = @(
    'owner_equal=false',
    'group_equal=false',
    'dacl_binary_equal=false',
    'sacl_binary_equal=false'
)
for ($mutationIndex = 0;
    $mutationIndex -lt $mutatedSecuritySddls.Count;
    $mutationIndex++) {{
    $mutatedSecuritySddl = $mutatedSecuritySddls[$mutationIndex]
    $mutatedSecurity = New-Object Security.AccessControl.FileSecurity
    $mutatedSecurity.SetSecurityDescriptorSddlForm(
        $mutatedSecuritySddl,
        $allSections
    )
    $mutationDiagnostic =
        Get-TicketboxWindowsSecurityDescriptorDifferenceDiagnostic `
            -Left $semanticSecurityBytes `
            -Right $mutatedSecurity.GetSecurityDescriptorBinaryForm()
    if (-not $mutationDiagnostic.Contains(
        $expectedMutationDiagnostics[$mutationIndex]
    )) {{
        throw 'security diagnostic missed an authority component mutation'
    }}
    if ($mutationDiagnostic.Contains($identitySid) -or
        $mutationDiagnostic.Contains('S-1-')) {{
        throw 'security diagnostic leaked mutated descriptor identity content'
    }}
    if (Test-TicketboxWindowsSecurityDescriptorEquals `
        -Left $semanticSecurityBytes `
        -Right $mutatedSecurity.GetSecurityDescriptorBinaryForm()) {{
        throw 'descriptor comparison ignored an owner/group/DACL/SACL mutation'
    }}
    if (Test-TicketboxWindowsSecurityDescriptorEquals `
        -Left $semanticSecurityBytes `
        -Right $mutatedSecurity.GetSecurityDescriptorBinaryForm() `
        -AllowWindowsReplacementDaclProjection) {{
        throw 'ReplaceFileW projection ignored an authority component mutation'
    }}
    $projectedMutation = New-Object `
        Security.AccessControl.RawSecurityDescriptor(
            $autoInheritedSecurityBytes,
            0
        )
    $mutationDescriptor = New-Object `
        Security.AccessControl.RawSecurityDescriptor(
            $mutatedSecurity.GetSecurityDescriptorBinaryForm(),
            0
        )
    switch ($mutationIndex) {{
        0 {{ $projectedMutation.Owner = $mutationDescriptor.Owner }}
        1 {{ $projectedMutation.Group = $mutationDescriptor.Group }}
        2 {{
            $projectedMutation.DiscretionaryAcl =
                $mutationDescriptor.DiscretionaryAcl
        }}
        3 {{ $projectedMutation.SystemAcl = $mutationDescriptor.SystemAcl }}
    }}
    $projectedMutationBytes =
        New-Object byte[] $projectedMutation.BinaryLength
    $projectedMutation.GetBinaryForm($projectedMutationBytes,0)
    if (Test-TicketboxWindowsSecurityDescriptorEquals `
        -Left $projectedMutationBytes `
        -Right $inheritanceSecurityBytes `
        -AllowWindowsReplacementDaclProjection) {{
        throw 'ReplaceFileW projection ignored a projected authority mutation'
    }}
}}
$target = {_ps_literal(target)}
$replacement = {_ps_literal(replacement)}
$backup = {_ps_literal(backup)}
$mutation = {_ps_literal(mutation)}
[IO.File]::WriteAllText($target,'target',[Text.Encoding]::UTF8)
[IO.File]::WriteAllText($replacement,'replacement',[Text.Encoding]::UTF8)

function Get-TestDescriptorBytes {{
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    $sections =
        [Security.AccessControl.AccessControlSections]::Access -bor
        [Security.AccessControl.AccessControlSections]::Owner -bor
        [Security.AccessControl.AccessControlSections]::Group
    $security = if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::GetAccessControl($item,$sections)
    }}
    else {{ $item.GetAccessControl($sections) }}
    return $security.GetSecurityDescriptorBinaryForm()
}}
function Set-TestUniqueTargetDescriptor {{
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    $sections =
        [Security.AccessControl.AccessControlSections]::Access -bor
        [Security.AccessControl.AccessControlSections]::Owner -bor
        [Security.AccessControl.AccessControlSections]::Group
    $security = if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::GetAccessControl($item,$sections)
    }}
    else {{ $item.GetAccessControl($sections) }}
    $security.SetAccessRuleProtection($true,$false)
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $security.SetAccessRule($rule)
    if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::SetAccessControl($item,$security)
    }}
    else {{ $item.SetAccessControl($security) }}
}}

Set-TestUniqueTargetDescriptor $target
$targetDescriptor = Get-TestDescriptorBytes $target
$replacementDescriptor = Get-TestDescriptorBytes $replacement
if (Test-TicketboxWindowsByteArrayEquals $targetDescriptor $replacementDescriptor) {{
    throw 'descriptor fixture was vacuous before ReplaceFileW'
}}
$replaceResult = Replace-TicketboxFileDurablePreservingMetadata `
    -Replacement $replacement `
    -Destination $target `
    -Backup $backup
if (-not $replaceResult.Succeeded -or $replaceResult.NativeErrorCode -ne 0) {{
    throw 'ReplaceFileW unexpectedly reported failure'
}}
$replaceDescriptor = Get-TestDescriptorBytes $target
if (-not (Test-TicketboxWindowsByteArrayEquals `
    $targetDescriptor `
    $replaceDescriptor)) {{
    throw 'ReplaceFileW failed to retain the replaced-file descriptor'
}}
if ([IO.File]::ReadAllText($target,[Text.Encoding]::UTF8) -cne 'replacement') {{
    throw 'ReplaceFileW did not publish replacement bytes'
}}
[IO.File]::Delete($backup)

[IO.File]::WriteAllText($mutation,'mutation',[Text.Encoding]::UTF8)
$mutationDescriptor = Get-TestDescriptorBytes $mutation
if (Test-TicketboxWindowsByteArrayEquals $targetDescriptor $mutationDescriptor) {{
    throw 'descriptor mutation fixture was vacuous before MoveFileEx'
}}
Move-TicketboxFileDurable `
    -Source $mutation `
    -Destination $target `
    -ReplaceExisting
$moveDescriptor = Get-TestDescriptorBytes $target
if (Test-TicketboxWindowsByteArrayEquals $targetDescriptor $moveDescriptor) {{
    throw 'MoveFileEx mutation unexpectedly preserved target descriptor'
}}
if (-not (Test-TicketboxWindowsByteArrayEquals `
    $mutationDescriptor `
    $moveDescriptor)) {{
    throw 'MoveFileEx mutation did not replace with source descriptor'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
@pytest.mark.parametrize("native_error", [1175, 1176, 1177])
def test_replacefile_partial_outcomes_and_crash_retry_reconcile_without_copy_loss(
    engine: str,
    native_error: int,
    tmp_path: Path,
) -> None:
    target = tmp_path / f"{Path(engine).stem}-{native_error}-pg_hba.conf"
    script = f"""
$ErrorActionPreference = 'Stop'
{_STUBS}
. {_ps_literal(SCRIPT)}
$target = {_ps_literal(target)}
$replacementPath = Join-Path (Split-Path -Parent $target) `
    ('.' + [IO.Path]::GetFileName($target) + '.ticketbox-c07-replacement')
$stagingPath = Join-Path (Split-Path -Parent $target) `
    ('.' + [IO.Path]::GetFileName($target) + '.ticketbox-c07-replacement-staging')
$backupPath = Join-Path (Split-Path -Parent $target) `
    ('.' + [IO.Path]::GetFileName($target) + '.ticketbox-c07-backup')
$oldBytes = [Text.Encoding]::UTF8.GetBytes("old-auth`r`n")
$newBytes = [Text.Encoding]::UTF8.GetBytes("new-auth`r`n")
$oldSha = Get-TicketboxC07SuperuserRecoverySha256 $oldBytes
$newSha = Get-TicketboxC07SuperuserRecoverySha256 $newBytes
$script:testSecurity = [byte[]](7,8,9)
$nativeError = {native_error}

function Enter-TicketboxC07SuperuserRecoverySecurityPrivilege {{
    param([string]$PrivilegeName)
    if ($PrivilegeName -cne 'SeSecurityPrivilege') {{
        throw "unexpected privilege: $PrivilegeName"
    }}
    $scope = [pscustomobject]@{{}}
    Add-Member -InputObject $scope -MemberType ScriptMethod -Name Dispose -Value {{}}
    return $scope
}}
function New-TicketboxC07SuperuserRecoveryCreationSecurity {{ param($SecurityBytes); return 'stub' }}
function Get-TicketboxC07SuperuserRecoveryCreationSecuritySddl {{ param($SecurityBytes); return 'O:stubG:stubD:stub' }}
function New-TicketboxProtectedFileStream {{
    param($Path,$Security)
    return New-Object IO.FileStream(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
}}
function Get-TicketboxC07SuperuserRecoveryAuthFile {{
    param($Path,$Label)
    if (-not [IO.File]::Exists($Path)) {{ throw "$Label missing" }}
    $bytes = [IO.File]::ReadAllBytes($Path)
    return [pscustomobject]@{{
        Path = [IO.Path]::GetFullPath($Path)
        Bytes = $bytes
        Sha256 = Get-TicketboxC07SuperuserRecoverySha256 $bytes
        SecurityBytes = $script:testSecurity
    }}
}}
function Move-TicketboxFileDurable {{
    param($Source,$Destination,[switch]$ReplaceExisting)
    if ($ReplaceExisting -and [IO.File]::Exists($Destination)) {{
        [IO.File]::Delete($Destination)
    }}
    [IO.File]::Move($Source,$Destination)
}}
function Invoke-TestPartialOutcome {{
    param($Replacement,$Destination,$Backup,[switch]$Crash)
    if ($nativeError -eq 1177) {{
        [IO.File]::Move($Destination,$Backup)
    }}
    if ($Crash) {{ throw "injected crash after native $nativeError partial outcome" }}
    return [pscustomobject]@{{ Succeeded = $false; NativeErrorCode = $nativeError }}
}}
function Set-TestSuccessfulReplace {{
    function global:Replace-TicketboxFileDurablePreservingMetadata {{
        param($Replacement,$Destination,$Backup)
        [IO.File]::Move($Destination,$Backup)
        [IO.File]::Move($Replacement,$Destination)
        return [pscustomobject]@{{ Succeeded = $true; NativeErrorCode = 0 }}
    }}
}}
function Assert-TestConverged {{
    if (-not [IO.File]::Exists($target) -or
        (Get-TicketboxC07SuperuserRecoverySha256 (
            [IO.File]::ReadAllBytes($target)
        )) -cne $newSha -or
        [IO.File]::Exists($replacementPath) -or
        [IO.File]::Exists($stagingPath) -or
        [IO.File]::Exists($backupPath)) {{
        throw "native $nativeError did not converge without sidecar residue"
    }}
}}

# Native FALSE must be reconciled from actual names, not treated as a
# side-effect-free exception.  1175/1176 retain the retry sidecar; 1177 is
# immediately recoverable from exact backup + inherited replacement.
[IO.File]::WriteAllBytes($target,$oldBytes)
function Replace-TicketboxFileDurablePreservingMetadata {{
    param($Replacement,$Destination,$Backup)
    return Invoke-TestPartialOutcome $Replacement $Destination $Backup
}}
$firstRejected = $false
$firstError = ''
try {{
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $target `
        -Bytes $newBytes `
        -SecurityBytes $script:testSecurity `
        -ExpectedSha256 $newSha `
        -PreviousSha256 $oldSha `
        -Label "native $nativeError false" | Out-Null
}}
catch {{ $firstRejected = $true; $firstError = $_.Exception.Message }}
if ($nativeError -eq 1177) {{
    if ($firstRejected) {{
        throw "1177 exact partial state did not reconcile: $firstError"
    }}
}}
else {{
    if (-not $firstRejected -or
        -not [IO.File]::Exists($target) -or
        -not [IO.File]::Exists($replacementPath) -or
        [IO.File]::Exists($backupPath)) {{
        throw "native $nativeError FALSE lost its retry-safe state: $firstError"
    }}
    Set-TestSuccessfulReplace
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $target -Bytes $newBytes -SecurityBytes $script:testSecurity `
        -ExpectedSha256 $newSha -PreviousSha256 $oldSha `
        -Label "native $nativeError retry" | Out-Null
}}
Assert-TestConverged

# A process crash may happen after the Win32 side effect and before the caller
# sees the return value.  A fresh invocation must discover and converge the
# deterministic three-path state without deleting the only valid copy.
[IO.File]::WriteAllBytes($target,$oldBytes)
function Replace-TicketboxFileDurablePreservingMetadata {{
    param($Replacement,$Destination,$Backup)
    return Invoke-TestPartialOutcome $Replacement $Destination $Backup -Crash
}}
$crashed = $false
try {{
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $target -Bytes $newBytes -SecurityBytes $script:testSecurity `
        -ExpectedSha256 $newSha -PreviousSha256 $oldSha `
        -Label "native $nativeError crash" | Out-Null
}}
catch {{ $crashed = $true }}
if (-not $crashed) {{ throw 'injected crash was not observed' }}
if (-not [IO.File]::Exists($replacementPath)) {{
    throw 'crash deleted the desired replacement copy'
}}
if ($nativeError -eq 1177) {{
    if ([IO.File]::Exists($target) -or -not [IO.File]::Exists($backupPath)) {{
        throw '1177 crash window names do not match the documented state'
    }}
}}
else {{
    if (-not [IO.File]::Exists($target) -or [IO.File]::Exists($backupPath)) {{
        throw "$nativeError crash window did not retain original names"
    }}
}}
Set-TestSuccessfulReplace
Write-TicketboxC07SuperuserRecoveryAuthFile `
    -Path $target -Bytes $newBytes -SecurityBytes $script:testSecurity `
    -ExpectedSha256 $newSha -PreviousSha256 $oldSha `
    -Label "native $nativeError crash retry" | Out-Null
Assert-TestConverged

# A crash while writing the unpublished staging file must not poison the
# deterministic replacement name.  A fresh invocation may discard only that
# invalid staging file because the exact previous destination/full descriptor
# is still authoritative and no backup/replacement exists.
[IO.File]::WriteAllBytes($target,$oldBytes)
function New-TicketboxProtectedFileStream {{
    param($Path,$Security)
    $partial = [pscustomobject]@{{ Path = $Path }}
    Add-Member -InputObject $partial -MemberType ScriptMethod -Name Write -Value {{
        param($Buffer,$Offset,$Count)
        $prefixLength = [Math]::Min(3,$Count)
        $prefix = New-Object byte[] $prefixLength
        [Array]::Copy($Buffer,$Offset,$prefix,0,$prefixLength)
        [IO.File]::WriteAllBytes([string]$this.Path,$prefix)
        throw 'injected crash during replacement staging write'
    }}
    Add-Member -InputObject $partial -MemberType ScriptMethod -Name Flush -Value {{
        param($Durable)
    }}
    Add-Member -InputObject $partial -MemberType ScriptMethod -Name Dispose -Value {{}}
    return $partial
}}
function Replace-TicketboxFileDurablePreservingMetadata {{
    throw 'ReplaceFileW must not run after a partial staging write'
}}
$stagingCrash = $false
try {{
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $target -Bytes $newBytes -SecurityBytes $script:testSecurity `
        -ExpectedSha256 $newSha -PreviousSha256 $oldSha `
        -Label "native $nativeError staging crash" | Out-Null
}}
catch {{ $stagingCrash = $true }}
if (-not $stagingCrash -or
    -not [IO.File]::Exists($stagingPath) -or
    [IO.File]::Exists($replacementPath) -or
    [IO.File]::Exists($backupPath) -or
    (Get-TicketboxC07SuperuserRecoverySha256 (
        [IO.File]::ReadAllBytes($target)
    )) -cne $oldSha) {{
    throw 'partial staging crash did not retain the exact previous authority'
}}
function New-TicketboxProtectedFileStream {{
    param($Path,$Security)
    return New-Object IO.FileStream(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
}}
Set-TestSuccessfulReplace
Write-TicketboxC07SuperuserRecoveryAuthFile `
    -Path $target -Bytes $newBytes -SecurityBytes $script:testSecurity `
    -ExpectedSha256 $newSha -PreviousSha256 $oldSha `
    -Label "native $nativeError staging crash retry" | Out-Null
Assert-TestConverged
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_auth_file_replace_preserves_explicit_sacl_and_mutation_is_killed(
    engine: str,
    tmp_path: Path,
) -> None:
    target = tmp_path / f"{Path(engine).stem}-pg_hba.conf"
    original = b"# original\r\n"
    target.write_bytes(original)
    script = f"""
$ErrorActionPreference = 'Stop'
. {_ps_literal(SAFETY)}
. {_ps_literal(SCRIPT)}
$path = {_ps_literal(target)}
$original = [Text.Encoding]::UTF8.GetBytes("# original`r`n")
[IO.File]::WriteAllBytes($path,$original)
$item = Get-Item -LiteralPath $path -Force
$baseSections =
    [Security.AccessControl.AccessControlSections]::Access -bor
    [Security.AccessControl.AccessControlSections]::Owner -bor
    [Security.AccessControl.AccessControlSections]::Group
$baseSecurity = if ($PSVersionTable.PSEdition -eq 'Core') {{
    [IO.FileSystemAclExtensions]::GetAccessControl($item,$baseSections)
}}
else {{ $item.GetAccessControl($baseSections) }}
$baseSecurityBytes = $baseSecurity.GetSecurityDescriptorBinaryForm()

# Privilege loss must stop before the target bytes change.
function Enter-TicketboxC07SuperuserRecoverySecurityPrivilege {{
    param([string]$PrivilegeName)
    if ($PrivilegeName -cne 'SeSecurityPrivilege') {{
        throw "unexpected privilege: $PrivilegeName"
    }}
    throw 'injected SeSecurityPrivilege denial'
}}
$denied = $false
try {{
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $path `
        -Bytes ([Text.Encoding]::UTF8.GetBytes("# denied`r`n")) `
        -SecurityBytes $baseSecurityBytes `
        -ExpectedSha256 ('0' * 64) `
        -PreviousSha256 (
            Get-TicketboxC07SuperuserRecoverySha256 $original
        ) `
        -Label 'privilege-denied mutation' | Out-Null
}}
catch {{ $denied = $true }}
if (-not $denied -or
    -not (Test-TicketboxWindowsByteArrayEquals `
        ([IO.File]::ReadAllBytes($path)) `
        $original)) {{
    throw 'privilege denial did not fail before auth-file mutation'
}}

# Restore the production privilege function after the injected denial.
. {_ps_literal(SCRIPT)}
$probe = $null
try {{
    $probe = Enter-TicketboxC07SuperuserRecoverySecurityPrivilege `
        -PrivilegeName 'SeSecurityPrivilege'
}}
catch {{
    'SKIP_SACL_OK'
    exit 0
}}
try {{
    $item = Get-Item -LiteralPath $path -Force
    $allSections = [Security.AccessControl.AccessControlSections]::All
    $security = if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::GetAccessControl($item,$allSections)
    }}
    else {{ $item.GetAccessControl($allSections) }}
    $auditRule = New-Object Security.AccessControl.FileSystemAuditRule(
        [Security.Principal.WindowsIdentity]::GetCurrent().Name,
        [Security.AccessControl.FileSystemRights]::WriteData,
        [Security.AccessControl.InheritanceFlags]::None,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AuditFlags]::Success
    )
    [void]$security.AddAuditRule($auditRule)
    if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::SetAccessControl($item,$security)
    }}
    else {{ $item.SetAccessControl($security) }}
    $persistedSecurity = if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::GetAccessControl($item,$allSections)
    }}
    else {{ $item.GetAccessControl($allSections) }}
    $explicitAuditRules = @(
        $persistedSecurity.GetAuditRules(
            $true,
            $false,
            [Security.Principal.NTAccount]
        ) | Where-Object {{
            [string]$_.IdentityReference -ceq
                [Security.Principal.WindowsIdentity]::GetCurrent().Name -and
            ($_.FileSystemRights -band
                [Security.AccessControl.FileSystemRights]::WriteData) -ne 0 -and
            ($_.AuditFlags -band
                [Security.AccessControl.AuditFlags]::Success) -ne 0
        }}
    )
    if ($explicitAuditRules.Count -lt 1) {{
        throw 'explicit audit ACE was not persisted before replacement'
    }}
}}
finally {{ $probe.Dispose() }}

$captured = Get-TicketboxC07SuperuserRecoveryAuthFile `
    -Path $path `
    -Label 'SACL target'
$replacement = [Text.Encoding]::UTF8.GetBytes("# replacement`r`n")
$replacementSha = Get-TicketboxC07SuperuserRecoverySha256 $replacement
Write-TicketboxC07SuperuserRecoveryAuthFile `
    -Path $path `
    -Bytes $replacement `
    -SecurityBytes $captured.SecurityBytes `
    -ExpectedSha256 $replacementSha `
    -PreviousSha256 (
        Get-TicketboxC07SuperuserRecoverySha256 $original
    ) `
    -Label 'SACL-preserving replacement'
$persisted = Get-TicketboxC07SuperuserRecoveryAuthFile `
    -Path $path `
    -Label 'SACL-preserving replacement'
if ($persisted.Sha256 -cne $replacementSha -or
    -not (Test-TicketboxWindowsSecurityDescriptorEquals `
        -Left $persisted.SecurityBytes `
        -Right $captured.SecurityBytes `
        -AllowWindowsReplacementDaclProjection)) {{
    throw 'ReplaceFileW did not preserve the captured security authority'
}}

# Mutation intent: publish a source whose SACL was deliberately corrupted via
# the former MoveFileEx path. A same-volume move preserves the source security
# descriptor, so the strict candidate and full-SACL verification must reject it.
function Replace-TicketboxFileDurablePreservingMetadata {{
    param($Replacement,$Destination,$Backup)
    $replacementItem = Get-Item -LiteralPath $Replacement -Force
    $allSections = [Security.AccessControl.AccessControlSections]::All
    $replacementSecurity = if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::GetAccessControl(
            $replacementItem,
            $allSections
        )
    }}
    else {{ $replacementItem.GetAccessControl($allSections) }}
    $replacementSecurity.PurgeAuditRules(
        [Security.Principal.WindowsIdentity]::GetCurrent().User
    )
    if ($PSVersionTable.PSEdition -eq 'Core') {{
        [IO.FileSystemAclExtensions]::SetAccessControl(
            $replacementItem,
            $replacementSecurity
        )
    }}
    else {{ $replacementItem.SetAccessControl($replacementSecurity) }}
    $mutatedSource = Get-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $Replacement `
        -Label 'MoveFileEx mutation source'
    if (Test-TicketboxWindowsSecurityDescriptorEquals `
        -Left $mutatedSource.SecurityBytes `
        -Right $captured.SecurityBytes) {{
        throw 'MoveFileEx mutation source retained the captured SACL'
    }}
    Move-TicketboxFileDurable `
        -Source $Replacement `
        -Destination $Destination `
        -ReplaceExisting
    return [pscustomobject]@{{ Succeeded = $true; NativeErrorCode = 0 }}
}}
$mutatedBytes = [Text.Encoding]::UTF8.GetBytes("# mutated-move`r`n")
$mutationRejected = $false
try {{
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $path `
        -Bytes $mutatedBytes `
        -SecurityBytes $captured.SecurityBytes `
        -ExpectedSha256 (
            Get-TicketboxC07SuperuserRecoverySha256 $mutatedBytes
        ) `
        -PreviousSha256 $replacementSha `
        -Label 'MoveFileEx mutation' | Out-Null
}}
catch {{ $mutationRejected = $true }}
if (-not $mutationRejected) {{
    throw 'MoveFileEx mutation retained authority unexpectedly'
}}
$mutated = Get-TicketboxC07SuperuserRecoveryAuthFile `
    -Path $path `
    -Label 'MoveFileEx mutation result'
if (Test-TicketboxWindowsSecurityDescriptorEquals `
    -Left $mutated.SecurityBytes `
    -Right $captured.SecurityBytes) {{
    throw 'MoveFileEx mutation did not exercise explicit-SACL loss'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    output = result.stdout.strip().splitlines()[-1]
    if output == "SKIP_SACL_OK":
        if any(
            os.environ.get(marker, "").strip().lower() == "true" for marker in ("CI", "GITHUB_ACTIONS", "GITEA_ACTIONS")
        ):
            pytest.fail("Windows packaging CI lacks SeSecurityPrivilege; explicit-SACL preservation is unqualified")
        pytest.skip("current token lacks SeSecurityPrivilege; fail-closed path passed")
    assert output == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_artifact_is_strict_cross_host_and_preserves_original_bytes(
    engine: str,
    tmp_path: Path,
) -> None:
    hba = tmp_path / "pg_hba.conf"
    ident = tmp_path / "pg_ident.conf"
    artifact_path = tmp_path / "c07-superuser-recovery.pgpass"
    hba.write_bytes(b"\xef\xbb\xbf# original-hba\r\nhost all all 127.0.0.1/32 scram-sha-256\r\n")
    ident.write_bytes(b"# original-ident\r\n")
    script = f"""
{_STUBS}
. {_ps_literal(SCRIPT)}
$hbaBytes = [IO.File]::ReadAllBytes({_ps_literal(hba)})
$identBytes = [IO.File]::ReadAllBytes({_ps_literal(ident)})
$HostContext = [pscustomobject]@{{
    ClusterSystemIdentifier = '7123456789012345678'
    PgData = {_ps_literal(tmp_path)}
    Port = 55432
    PostgresqlConfSha256 = ('A' * 64)
    PostgresqlAutoConfSha256 = 'MISSING'
    PgVersionSha256 = ('B' * 64)
    Hba = [pscustomobject]@{{
        Path = {_ps_literal(hba)}
        Bytes = $hbaBytes
        Sha256 = Get-TicketboxC07SuperuserRecoverySha256 $hbaBytes
        SecurityBytes = [byte[]](1,2,3)
    }}
    Ident = [pscustomobject]@{{
        Path = {_ps_literal(ident)}
        Bytes = $identBytes
        Sha256 = Get-TicketboxC07SuperuserRecoverySha256 $identBytes
        SecurityBytes = [byte[]](4,5,6)
    }}
}}
$principal = [pscustomobject]@{{
    Name = 'MACHINE\\Family Owner'
    Sid = 'S-1-5-21-1-2-3-1001'
    Realm = 'MACHINE'
    SystemUsername = 'Family Owner@MACHINE'
}}
$created = New-TicketboxC07SuperuserRecoveryArtifact `
    -Host $HostContext `
    -Principal $principal `
    -ExpectedOperationId '11111111-1111-4111-8111-111111111111'
$persisted = Write-TicketboxC07SuperuserRecoveryArtifact `
    -Path {_ps_literal(artifact_path)} `
    -Artifact $created
$material = Assert-TicketboxC07SuperuserRecoveryArtifact `
    -Artifact $persisted `
    -Host $HostContext
if (-not (Test-TicketboxWindowsByteArrayEquals $material.HbaOriginalBytes $hbaBytes)) {{
    throw 'hba original bytes were not preserved'
}}
if (-not (Test-TicketboxWindowsByteArrayEquals $material.IdentOriginalBytes $identBytes)) {{
    throw 'ident original bytes were not preserved'
}}
if ($material.HbaTemporaryBytes[0] -ne 0xEF -or
    $material.HbaTemporaryBytes[1] -ne 0xBB -or
    $material.HbaTemporaryBytes[2] -ne 0xBF) {{
    throw 'UTF-8 BOM was not retained at byte zero'
}}
$text = [IO.File]::ReadAllText({_ps_literal(artifact_path)}, [Text.Encoding]::UTF8)
if ($text -match [regex]::Escape($persisted.secret) -and
    ($text -split "`n" | Where-Object {{ $_ -like '# *' -and $_ -match [regex]::Escape($persisted.secret) }})) {{
    throw 'secret leaked into recovery metadata'
}}
if (($text -split "`n" | Where-Object {{ $_ -like '127.0.0.1:*' }}).Count -ne 1) {{
    throw 'artifact is not the sole exact pgpass record'
}}
$lines = @($text.Split([char]"`n"))
$lines[2] = $lines[1]
[IO.File]::WriteAllText(
    {_ps_literal(artifact_path)},
    ($lines -join "`n"),
    (New-Object Text.UTF8Encoding($false, $true))
)
$rejected = $false
try {{ Read-TicketboxC07SuperuserRecoveryArtifact {_ps_literal(artifact_path)} }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'duplicate/out-of-order artifact field was accepted' }}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_auth_publication_and_every_restore_crash_window_are_safe(
    engine: str,
    tmp_path: Path,
) -> None:
    hba = tmp_path / "pg_hba.conf"
    ident = tmp_path / "pg_ident.conf"
    script = f"""
{_STUBS}
. {_ps_literal(SCRIPT)}
$script:events = New-Object System.Collections.Generic.List[string]
$security = [byte[]](7,8,9)
function Get-TicketboxC07SuperuserRecoveryAuthFile {{
    param($Path, $Label)
    $bytes = [IO.File]::ReadAllBytes($Path)
    return [pscustomobject]@{{
        Path = $Path
        Bytes = $bytes
        Sha256 = Get-TicketboxC07SuperuserRecoverySha256 $bytes
        SecurityBytes = $security
    }}
}}
function Write-TicketboxC07SuperuserRecoveryAuthFile {{
    param($Path, $Bytes, $SecurityBytes, $ExpectedSha256, $PreviousSha256, $Label)
    $script:events.Add("write:$Label")
    [IO.File]::WriteAllBytes($Path, $Bytes)
}}
function Invoke-TicketboxC07SuperuserRecoveryReload {{
    param($HostContext, $TimeoutMilliseconds)
    $script:events.Add('reload')
}}
function Set-TicketboxC07SuperuserRecoveryStage {{
    param($Path, $Artifact, $Stage)
    $Artifact.stage = $Stage
    $script:events.Add("stage:$Stage")
    return $Artifact
}}
$hbaOriginal = [Text.Encoding]::UTF8.GetBytes("hba-original`n")
$identOriginal = [Text.Encoding]::UTF8.GetBytes("ident-original`n")
$hbaTemporary = [Text.Encoding]::UTF8.GetBytes("hba-temporary`n")
$identTemporary = [Text.Encoding]::UTF8.GetBytes("ident-temporary`n")
$artifact = [pscustomobject]@{{
    stage = 'captured'
    hba_path = {_ps_literal(hba)}
    ident_path = {_ps_literal(ident)}
    hba_original_sha256 = Get-TicketboxC07SuperuserRecoverySha256 $hbaOriginal
    ident_original_sha256 = Get-TicketboxC07SuperuserRecoverySha256 $identOriginal
    hba_temporary_sha256 = Get-TicketboxC07SuperuserRecoverySha256 $hbaTemporary
    ident_temporary_sha256 = Get-TicketboxC07SuperuserRecoverySha256 $identTemporary
}}
$material = [pscustomobject]@{{
    HbaOriginalBytes = $hbaOriginal
    IdentOriginalBytes = $identOriginal
    HbaTemporaryBytes = $hbaTemporary
    IdentTemporaryBytes = $identTemporary
    HbaSecurityBytes = $security
    IdentSecurityBytes = $security
}}
$HostContext = [pscustomobject]@{{}}
[IO.File]::WriteAllBytes({_ps_literal(hba)}, $hbaOriginal)
[IO.File]::WriteAllBytes({_ps_literal(ident)}, $identOriginal)
$artifact = Publish-TicketboxC07SuperuserRecoverySspi `
    -Host $HostContext -ArtifactPath 'unused' -Artifact $artifact -Material $material
$artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
    -Host $HostContext -ArtifactPath 'unused' -Artifact $artifact -Material $material
$expected = @(
    'write:publish temporary pg_ident.conf',
    'stage:sspi_ident_published',
    'reload',
    'write:publish temporary pg_hba.conf',
    'stage:sspi_hba_published',
    'write:restore pg_hba.conf',
    'write:restore pg_ident.conf',
    'reload',
    'stage:auth_files_restored'
)
if (($script:events -join '|') -cne ($expected -join '|')) {{
    throw "publication/restore order mismatch: $($script:events -join '|')"
}}

# Crash after ident publish: original HBA remains authoritative; restore ident+reload.
$script:events.Clear()
[IO.File]::WriteAllBytes({_ps_literal(hba)}, $hbaOriginal)
[IO.File]::WriteAllBytes({_ps_literal(ident)}, $identTemporary)
$artifact.stage = 'sspi_ident_published'
$artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
    -Host $HostContext -ArtifactPath 'unused' -Artifact $artifact -Material $material
if (($script:events -join '|') -cne
    'write:restore pg_ident.conf|reload|stage:auth_files_restored') {{
    throw 'ident-only crash did not converge'
}}

# Crash while restoring: HBA is already original while ident is temporary.
$script:events.Clear()
[IO.File]::WriteAllBytes({_ps_literal(hba)}, $hbaOriginal)
[IO.File]::WriteAllBytes({_ps_literal(ident)}, $identTemporary)
$artifact.stage = 'credential_rotated'
$artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
    -Host $HostContext -ArtifactPath 'unused' -Artifact $artifact -Material $material
if (($script:events -join '|') -cne
    'write:restore pg_ident.conf|reload|stage:auth_files_restored') {{
    throw 'restore crash did not converge'
}}

# Impossible/unsafe pair from an interrupted external write: temporary HBA with
# original ident must close HBA first, never republish the map implicitly.
$script:events.Clear()
[IO.File]::WriteAllBytes({_ps_literal(hba)}, $hbaTemporary)
[IO.File]::WriteAllBytes({_ps_literal(ident)}, $identOriginal)
$artifact.stage = 'sspi_hba_published'
$artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
    -Host $HostContext -ArtifactPath 'unused' -Artifact $artifact -Material $material
if (($script:events -join '|') -cne
    'write:restore pg_hba.conf|stage:auth_files_restored') {{
    throw 'HBA-first safety recovery did not converge'
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "OK"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_expired_exact_verifier_after_action_is_retired_through_sspi(
    engine: str,
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "c07-superuser-recovery.pgpass"
    artifact_path.write_text("owned-by-test\n", encoding="ascii")
    script = f"""
{_STUBS}
. {_ps_literal(SCRIPT)}
$script:events = New-Object System.Collections.Generic.List[string]
$script:cleared = $false
$script:artifact = [pscustomobject]@{{
    stage = 'action_succeeded'
    operation_id = '11111111-1111-4111-8111-111111111111'
    principal_name = 'MACHINE\\Family Owner'
    principal_sid = 'S-1-5-21-1-2-3-1001'
    sspi_system_username = 'Family Owner@MACHINE'
    sspi_realm = 'MACHINE'
    secret = ('A' * 64)
}}
$script:material = [pscustomobject]@{{}}
$script:databaseHost = [pscustomobject]@{{
    ClusterSystemIdentifier = '7123456789012345678'
    PgData = {_ps_literal(tmp_path)}
    Port = 55432
}}
function Assert-TicketboxC07SuperuserRecoveryDependencies {{}}
function Assert-TicketboxC07SuperuserRecoveryAdministrator {{}}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
function Assert-TicketboxC07SuperuserRecoveryArtifactPath {{
    param($Path)
    return $Path
}}
function Resolve-TicketboxC07SuperuserRecoveryHost {{
    param($HostAuthority)
    return $script:databaseHost
}}
function Get-TicketboxC07SuperuserRecoveryPrincipal {{
    return [pscustomobject]@{{
        Name = 'MACHINE\\Family Owner'
        Sid = 'S-1-5-21-1-2-3-1001'
        SystemUsername = 'Family Owner@MACHINE'
        Realm = 'MACHINE'
    }}
}}
function Read-TicketboxC07SuperuserRecoveryArtifact {{
    param($Path)
    return $script:artifact
}}
function Assert-TicketboxC07SuperuserRecoveryArtifact {{
    param($Artifact, $HostContext)
    return $script:material
}}
function Restore-TicketboxC07SuperuserRecoveryAuthFiles {{
    param($HostContext, $ArtifactPath, $Artifact, $Material)
    $script:events.Add('restore')
    return $Artifact
}}
function Test-TicketboxC07SuperuserRecoveryScramCredential {{
    param($HostContext, $ArtifactPath)
    $script:events.Add('scram:inactive')
    return $false
}}
function Publish-TicketboxC07SuperuserRecoverySspi {{
    param($HostContext, $ArtifactPath, $Artifact, $Material)
    $script:events.Add('publish:sspi')
    return $Artifact
}}
function Invoke-TicketboxC07SuperuserRecoveryReadPasswordStateViaSspi {{
    param($HostContext, $Artifact, $Secret)
    if ($script:cleared) {{
        $script:events.Add('state:null')
    }}
    else {{
        $script:events.Add('state:expired-exact-verifier')
    }}
    return [pscustomobject]@{{
        Login = $true
        PasswordNull = $script:cleared
        PasswordMatchesRecovery = -not $script:cleared
    }}
}}
function Invoke-TicketboxC07SuperuserRecoveryPsql {{
    param(
        $HostContext,
        $Authentication,
        $Sql,
        $Label,
        [AllowEmptyString()]$ArtifactPath = ''
    )
    if ($Authentication -cne 'sspi') {{
        throw "expired-verifier retirement used $Authentication"
    }}
    if (-not [string]::IsNullOrEmpty($ArtifactPath)) {{
        throw 'SSPI retirement incorrectly consumed pgpass'
    }}
    $script:events.Add('clear:sspi')
    $script:cleared = $true
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = (
            "postgres`tpostgres`t7123456789012345678`t" +
            "{str(tmp_path).replace(chr(92), chr(92) * 2)}`t55432`ttrue`ttrue`n"
        )
    }}
}}
function Set-TicketboxC07SuperuserRecoveryStage {{
    param($Path, $Artifact, $Stage)
    $Artifact.stage = $Stage
    $script:events.Add("stage:$Stage")
    return $Artifact
}}
function Remove-TicketboxC07CompletedSuperuserRecoveryArtifact {{
    param($Path, $Artifact, $Material)
    $script:events.Add("remove:$($Artifact.stage)")
}}
$secret = New-Object Security.SecureString
$secret.AppendChar('x')
$capability = [pscustomobject][ordered]@{{
    Schema = 'ticketbox-postgresql-superuser-capability-v1'
    OperationId = '11111111-1111-4111-8111-111111111111'
    RecoveryArtifactPath = {_ps_literal(artifact_path)}
    HostContext = $script:databaseHost
    Secret = $secret
    Closed = $false
}}
Revoke-TicketboxC07SuperuserCapability `
    -Capability $capability `
    -ExpectedOperationId $capability.OperationId `
    -LifecycleLock @{{}}
if (-not $capability.Closed) {{ throw 'revoked capability remained open' }}
$expected = @(
    'restore',
    'scram:inactive',
    'publish:sspi',
    'state:expired-exact-verifier',
    'clear:sspi',
    'state:null',
    'restore',
    'stage:password_cleared',
    'stage:completed',
    'remove:completed'
)
if (($script:events -join '|') -cne ($expected -join '|')) {{
    throw "expired-verifier convergence mismatch: $($script:events -join '|')"
}}
'OK'
"""
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "OK"


def _vendor_pg_bin() -> Path | None:
    local = PACKAGING / "vendor" / "pg" / "bin"
    return local if local.is_dir() else None


def _require_or_skip_real_pg17_sspi(reason: str) -> None:
    required = os.environ.get("XPJ_REQUIRE_REAL_PG17_SSPI", "")
    if required not in {"", "0", "1"}:
        pytest.fail(
            "XPJ_REQUIRE_REAL_PG17_SSPI must be unset, 0, or 1",
            pytrace=False,
        )
    if required == "1":
        pytest.fail(reason, pytrace=False)
    pytest.skip(reason)


def test_real_pg17_sspi_gate_fails_closed_when_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XPJ_REQUIRE_REAL_PG17_SSPI", "1")
    with pytest.raises(
        pytest.fail.Exception,
        match="bundled PostgreSQL binaries are not available",
    ):
        _require_or_skip_real_pg17_sspi("bundled PostgreSQL binaries are not available")


def test_real_pg17_sspi_exact_principal_round_trip(tmp_path: Path) -> None:
    if sys.platform != "win32":
        _require_or_skip_real_pg17_sspi("SSPI is Windows-only")
    pg_bin = _vendor_pg_bin()
    if pg_bin is None:
        _require_or_skip_real_pg17_sspi("bundled PostgreSQL binaries are not available")
    required = {name: pg_bin / f"{name}.exe" for name in ("initdb", "pg_ctl", "psql")}
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        _require_or_skip_real_pg17_sspi("bundled PostgreSQL SSPI toolset is incomplete: " + ", ".join(sorted(missing)))

    data_dir = tmp_path / "pgdata"
    pwfile = tmp_path / "bootstrap-password"
    pwfile.write_text("temporary-bootstrap-only\n", encoding="ascii")
    init = subprocess.run(
        [
            str(required["initdb"]),
            "-D",
            str(data_dir),
            "-U",
            "postgres",
            "--auth-local=scram-sha-256",
            "--auth-host=scram-sha-256",
            "--encoding=UTF8",
            "--no-locale",
            f"--pwfile={pwfile}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=60,
        check=False,
    )
    assert init.returncode == 0, init.stderr
    pwfile.unlink()

    identity_name = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "[Console]::OutputEncoding = "
                "New-Object Text.UTF8Encoding($false); "
                "[Security.Principal.WindowsIdentity]::GetCurrent().Name"
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=10,
        check=True,
    ).stdout.strip()
    realm, account = identity_name.split("\\", 1)
    system_username = f"{account}@{realm}"

    def quote(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    map_name = "ticketbox_c07_sspi_test"
    ident = data_dir / "pg_ident.conf"
    ident.write_text(
        f'{map_name} {quote(system_username)} "postgres"\r\n' + ident.read_text(encoding="utf-8-sig"),
        encoding="mbcs",
    )
    hba = data_dir / "pg_hba.conf"
    hba.write_text(
        'host "postgres" "postgres" 127.0.0.1/32 sspi '
        "include_realm=1 compat_realm=1 upn_username=0 "
        f"map={map_name}\r\n" + hba.read_text(encoding="utf-8-sig"),
        encoding="utf-8",
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (data_dir / "postgresql.conf").open("a", encoding="ascii") as config:
        config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {port}\n")

    log = tmp_path / "postgres.log"
    start = subprocess.run(
        [
            str(required["pg_ctl"]),
            "start",
            "-D",
            str(data_dir),
            "-l",
            str(log),
            "-w",
            "-t",
            "30",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
        check=False,
    )
    assert start.returncode == 0, log.read_text(encoding="utf-8-sig", errors="replace")
    try:
        clean_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
        result = subprocess.run(
            [
                str(required["psql"]),
                "--no-psqlrc",
                "--no-password",
                "--tuples-only",
                "--no-align",
                "--dbname",
                (
                    f"postgresql://postgres@localhost:{port}/postgres"
                    "?hostaddr=127.0.0.1&require_auth=sspi"
                    "&sslmode=disable&connect_timeout=10"
                ),
                "--command",
                "SELECT session_user, current_user;",
            ],
            env=clean_env,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr + log.read_text(encoding="utf-8-sig", errors="replace")
        assert result.stdout.strip() == "postgres|postgres"
    finally:
        subprocess.run(
            [
                str(required["pg_ctl"]),
                "stop",
                "-D",
                str(data_dir),
                "-m",
                "fast",
                "-w",
                "-t",
                "30",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
            check=False,
        )
