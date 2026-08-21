from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

ROOT = Path(__file__).resolve().parents[3]
SAFETY = ROOT / "backend" / "packaging" / "windows_installation_safety.ps1"
SECURITY_ENTRY = ROOT / "backend" / "packaging" / "windows_security_primitives.ps1"
TOKEN_PRIVILEGE_NATIVE = ROOT / "backend" / "packaging" / "security_primitives" / "token_privilege_native.ps1"
SERVICE_LIFECYCLE = ROOT / "backend" / "packaging" / "windows_service_lifecycle.ps1"
DATABASE_SAFETY = ROOT / "backend" / "packaging" / "windows_database_safety.ps1"
PREPARE = ROOT / "backend" / "packaging" / "prepare_bundled_upgrade.ps1"
DATABASE = ROOT / "backend" / "packaging" / "windows_bundled_database.ps1"

_CREATOR_OWNER_HARNESS = r"""
$ErrorActionPreference = 'Stop'
. '__SAFETY__'
$targetAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$targetSid = ConvertTo-TicketboxAccountSid $targetAccount
$creatorTokenOwner = 'S-1-5-32-544'
if ($targetSid -ceq $creatorTokenOwner) {
    throw 'test requires the user SID and token-default group owner to differ'
}

function New-InheritedRule([bool]$directory, [bool]$inherited) {
    $flags = if ($directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    return [pscustomobject]@{
        IdentityReference = [Security.Principal.SecurityIdentifier]::new($targetSid)
        AccessControlType = [Security.AccessControl.AccessControlType]::Allow
        FileSystemRights = [Security.AccessControl.FileSystemRights]::FullControl
        InheritanceFlags = $flags
        PropagationFlags = [Security.AccessControl.PropagationFlags]::None
        IsInherited = $inherited
    }
}

$script:ObservedAcl = [pscustomobject]@{
    Owner = $creatorTokenOwner
    AreAccessRulesProtected = $false
    Access = @((New-InheritedRule $false $true))
}
function Get-TicketboxPathAcl([string]$Path) { return $script:ObservedAcl }

Assert-TicketboxRecoverableInheritedFileAcl `
    -Path '__FILE__' `
    -FullControlAccounts @($targetAccount) `
    -OwnerAccount $targetAccount

$script:ObservedAcl = [pscustomobject]@{
    Owner = $creatorTokenOwner
    AreAccessRulesProtected = $false
    Access = @((New-InheritedRule $true $true))
}
Assert-TicketboxRecoverableInheritedDirectoryAcl `
    -Path '__DIRECTORY__' `
    -FullControlAccounts @($targetAccount) `
    -OwnerAccount $targetAccount

$script:ObservedAcl = [pscustomobject]@{
    Owner = $creatorTokenOwner
    AreAccessRulesProtected = $false
    Access = @((New-InheritedRule $false $false))
}
$explicitRejected = $false
try {
    Assert-TicketboxRecoverableInheritedFileAcl `
        -Path '__FILE__' `
        -FullControlAccounts @($targetAccount) `
        -OwnerAccount $targetAccount
}
catch { $explicitRejected = $true }
if (-not $explicitRejected) { throw 'an explicit child ACE was accepted' }

$unknownOwnerRejected = $false
try {
    Assert-TicketboxRecoverableInheritedFileAcl `
        -Path '__FILE__' `
        -FullControlAccounts @($targetAccount) `
        -OwnerAccount 'Ticketbox\UnresolvableOwner'
}
catch { $unknownOwnerRejected = $true }
if (-not $unknownOwnerRejected) { throw 'an unresolvable final owner was accepted' }
"""


def _ps_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def test_protected_creation_keeps_atomic_acl_and_restore_privilege_contract() -> None:
    source = SAFETY.read_text(encoding="utf-8-sig")
    security_entry = SECURITY_ENTRY.read_text(encoding="utf-8-sig")
    privilege = TOKEN_PRIVILEGE_NATIVE.read_text(encoding="utf-8-sig")
    restore_adapter = source[
        source.index("function Enter-TicketboxRestorePrivilegeForSecurityDescriptor") : source.index(
            "function New-TicketboxProtectedFileSecurity"
        )
    ]
    directory = source[
        source.index("function Initialize-TicketboxProtectedDirectoryAtomically") : source.index(
            "function New-TicketboxProtectedFileStream"
        )
    ]
    protected_file = source[
        source.index("function New-TicketboxProtectedFileStream") : source.index(
            "function Write-TicketboxProtectedUtf8FileDurable"
        )
    ]
    existing_acl_update = source[
        source.index("function Set-TicketboxWritableOwnerForAclUpdate") : source.index(
            "function Set-TicketboxExactDirectoryAcl"
        )
    ]
    durable_writer = source[
        source.index("function Write-TicketboxProtectedUtf8FileDurable") : source.index(
            "function Initialize-TicketboxInstallerStateDirectory"
        )
    ]

    assert "public sealed class TicketboxWindowsSecurityPrivilegeScope" in privilege
    assert "LookupPrivilegeValue(null, privilegeName" in privilege
    assert "ErrorNotAllAssigned = 1300" in privilege
    assert "out scope.previousState" in privilege
    assert "ref previousState" in privilege
    assert "restoreError == ErrorNotAllAssigned" in privilege
    assert "TicketboxRestorePrivilegeScope" not in source
    assert "AdjustTokenPrivileges" not in source
    assert '"token_privilege_native.ps1"' in security_entry
    assert "if ($ownerSid -eq $currentUserSid)" in restore_adapter
    assert "Enter-TicketboxWindowsTokenPrivilege" in restore_adapter
    assert '-PrivilegeName "SeRestorePrivilege"' in restore_adapter
    assert "Enter-TicketboxRestorePrivilegeForSecurityDescriptor $security" in directory
    assert "DirectoryInfo($fullPath)).Create($security)" in directory
    assert "FileSystemAclExtensions]::CreateDirectory($security, $fullPath)" in directory
    assert "$restorePrivilege.Dispose()" in directory
    assert "Enter-TicketboxRestorePrivilegeForSecurityDescriptor $Security" in protected_file
    assert "FileSystemAclExtensions]::Create(" in protected_file
    assert "[System.Security.AccessControl.FileSecurity]$Security" in protected_file
    assert "$restorePrivilege.Dispose()" in protected_file
    assert 'Invoke-TicketboxIcaclsChecked $Path @("/setowner"' not in existing_acl_update
    assert "FileSystemRights]::ChangePermissions" in existing_acl_update
    assert "拒绝临时接管 owner" in existing_acl_update
    assert durable_writer.count("Set-TicketboxOwnerIfNeeded") == 2
    assert durable_writer.count("Assert-TicketboxExactFileAcl") == 2
    assert durable_writer.index("Assert-TicketboxExactFileAcl") < durable_writer.index("Move-TicketboxFileDurable")
    assert durable_writer.rindex("Assert-TicketboxExactFileAcl") > durable_writer.index("Move-TicketboxFileDurable")
    assert "New-Item" not in directory
    assert "New-Item" not in protected_file


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_inherited_dacl_shape_is_independent_of_creator_token_owner(
    engine: str,
    tmp_path: Path,
) -> None:
    """Windows inherits a DACL, but assigns ownership from the creator token."""

    root = tmp_path / f"creator-owner-{Path(engine).stem}"
    child_directory = root / "child"
    child_directory.mkdir(parents=True)
    child_file = child_directory / "receipt.txt"
    child_file.write_text("bounded authority", encoding="utf-8")
    harness = root / "creator-owner.ps1"
    script = (
        _CREATOR_OWNER_HARNESS.replace("__SAFETY__", _ps_literal(SAFETY))
        .replace("__FILE__", _ps_literal(child_file))
        .replace("__DIRECTORY__", _ps_literal(child_directory))
    )
    harness.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
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
        timeout=30,
    )
    assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_data_root_volume_capabilities_use_win32_feature_flags(
    engine: str,
    tmp_path: Path,
) -> None:
    source = SAFETY.read_text(encoding="utf-8-sig")
    native = source[
        source.index("public static class TicketboxDirectoryGuardNativeMethods") : source.index(
            "function Enter-TicketboxDirectoryMutationGuard"
        )
    ]
    domain = source[
        source.index("function Assert-TicketboxDataRootDomain") : source.index(
            "function Assert-TicketboxInstallRootDomain"
        )
    ]
    assert 'EntryPoint = "GetVolumeInformationW"' in native
    assert 'EntryPoint = "GetVolumePathNameW"' in native
    assert "FILE_PERSISTENT_ACLS" not in source
    assert "[uint32]$filePersistentAcls = 0x00000008" in source
    assert "[uint32]$fileReadOnlyVolume = 0x00080000" in source
    assert domain.index("Assert-TicketboxDataRootVolumeCapabilities") < domain.index("$full.Length -lt 8")

    harness = tmp_path / f"volume-capabilities-{Path(engine).stem}.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SAFETY)}'
$script:flags = [uint32]0x00000008
function Get-TicketboxVolumeDescriptorForPath {{
    param([string]$Path)
    return [pscustomobject]@{{
        MountPoint = 'X:\\'
        Identity = '\\\\?\\Volume{{11111111-1111-1111-1111-111111111111}}\\'
        FileSystemName = 'capability-test'
        FileSystemFlags = $script:flags
    }}
}}
$accepted = Assert-TicketboxDataRootVolumeCapabilities 'X:\\TicketboxData'
if ($accepted.FileSystemFlags -ne [uint32]0x00000008) {{
    throw 'persistent ACL volume was not accepted'
}}
$script:flags = [uint32]0
$rejected = $false
try {{ Assert-TicketboxDataRootVolumeCapabilities 'X:\\TicketboxData' | Out-Null }}
catch {{ $rejected = $_.Exception.Message -like '*不保存并强制执行 Windows ACL*' }}
if (-not $rejected) {{ throw 'non-ACL volume was accepted' }}
$script:flags = [uint32]0x00080008
$rejected = $false
try {{ Assert-TicketboxDataRootVolumeCapabilities 'X:\\TicketboxData' | Out-Null }}
catch {{ $rejected = $_.Exception.Message -like '*只读卷*' }}
if (-not $rejected) {{ throw 'read-only ACL volume was accepted' }}
""",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fresh_install_authority_gate_repairs_known_marker_residual_first() -> None:
    source = PREPARE.read_text(encoding="utf-8-sig")
    gate_start = source.index("function Assert-TicketboxPreparedDataRootAuthorityGate")
    gate_end = source.index("function Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded", gate_start)
    gate = source[gate_start:gate_end]

    fresh_start = gate.index('if ($Mode -ceq "fresh_install")')
    fresh_end = gate.index("        else {", fresh_start)
    fresh_branch = gate[fresh_start:fresh_end]
    repair = "Repair-TicketboxRecoverableDataRootMarkerAcl"
    strict_read = "Assert-TicketboxProtectedDataRootMarker"
    assert repair in fresh_branch
    assert fresh_branch.index(repair) < fresh_branch.index(strict_read)
    assert "-FullControlAccounts $FullControlAccounts" in fresh_branch
    assert "-OwnerAccount $OwnerAccount" in fresh_branch
    assert repair not in gate[fresh_end:]


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows token and NTFS contract")
@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_real_token_system_owner_creation_enables_and_restores_serestore(
    engine: str,
    tmp_path: Path,
) -> None:
    harness = tmp_path / "restore-privilege-contract.ps1"
    current_root = tmp_path / "current-owner"
    system_root = tmp_path / "system-owner"
    bootstrap_root = tmp_path / "system-bootstrap-owner"
    missing_directory = tmp_path / "missing-privilege-directory"
    missing_file_parent = tmp_path / "missing-privilege-file-parent"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class TicketboxTestRestorePrivilege
{{
    private const uint TokenQuery = 0x0008;
    private const uint TokenAdjustPrivileges = 0x0020;
    private const int TokenPrivileges = 3;
    private const int ErrorInsufficientBuffer = 122;
    private const int ErrorNotAllAssigned = 1300;

    [StructLayout(LayoutKind.Sequential)]
    private struct Luid {{ public uint LowPart; public int HighPart; }}

    [StructLayout(LayoutKind.Sequential)]
    private struct LuidAndAttributes {{ public Luid Luid; public uint Attributes; }}

    [StructLayout(LayoutKind.Sequential)]
    private struct TokenPrivilege {{ public uint Count; public LuidAndAttributes Item; }}

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool LookupPrivilegeValue(string system, string name, out Luid luid);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetTokenInformation(
        IntPtr token, int informationClass, IntPtr information, int length, out int returnLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool AdjustTokenPrivileges(
        IntPtr token, bool disableAll, ref TokenPrivilege state, int length,
        IntPtr previousState, IntPtr returnLength);

    public static long GetAttributes()
    {{
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), TokenQuery, out token))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {{
            Luid expected;
            if (!LookupPrivilegeValue(null, "SeRestorePrivilege", out expected))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            int length;
            GetTokenInformation(token, TokenPrivileges, IntPtr.Zero, 0, out length);
            if (Marshal.GetLastWin32Error() != ErrorInsufficientBuffer)
                throw new Win32Exception(Marshal.GetLastWin32Error());
            IntPtr buffer = Marshal.AllocHGlobal(length);
            try
            {{
                if (!GetTokenInformation(token, TokenPrivileges, buffer, length, out length))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                int count = Marshal.ReadInt32(buffer, 0);
                for (int index = 0; index < count; index++)
                {{
                    int offset = 4 + (index * 12);
                    uint low = unchecked((uint)Marshal.ReadInt32(buffer, offset));
                    int high = Marshal.ReadInt32(buffer, offset + 4);
                    if (low == expected.LowPart && high == expected.HighPart)
                        return unchecked((uint)Marshal.ReadInt32(buffer, offset + 8));
                }}
                return -1;
            }}
            finally {{ Marshal.FreeHGlobal(buffer); }}
        }}
        finally {{ CloseHandle(token); }}
    }}

    public static void Disable()
    {{
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), TokenQuery | TokenAdjustPrivileges, out token))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {{
            Luid luid;
            if (!LookupPrivilegeValue(null, "SeRestorePrivilege", out luid))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            TokenPrivilege state = new TokenPrivilege();
            state.Count = 1;
            state.Item = new LuidAndAttributes {{ Luid = luid, Attributes = 0 }};
            bool adjusted = AdjustTokenPrivileges(
                token, false, ref state, 0, IntPtr.Zero, IntPtr.Zero);
            int error = Marshal.GetLastWin32Error();
            if (!adjusted || error == ErrorNotAllAssigned)
                throw new Win32Exception(error);
        }}
        finally {{ CloseHandle(token); }}
    }}
}}
'@
. '{_ps_literal(SAFETY)}'
. '{_ps_literal(DATABASE)}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$systemAccounts = @('SYSTEM', 'BUILTIN\\Administrators')

try {{
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path '{_ps_literal(current_root)}' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
    Write-TicketboxProtectedUtf8FileDurable `
        -Path '{_ps_literal(current_root / "current.txt")}' `
        -Text 'current-owner' `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
    $currentOwner = (Get-TicketboxPathAcl '{_ps_literal(current_root)}').Owner
    if ($currentOwner -cne $currentSid) {{
        throw 'current-owner fast path changed the owner SID'
    }}
    $currentFileAcl = Get-TicketboxPathAcl '{_ps_literal(current_root / "current.txt")}'
    if (-not $currentFileAcl.AreAccessRulesProtected -or
        @($currentFileAcl.Access | Where-Object {{ $_.IsInherited }}).Count -ne 0) {{
        throw 'current-owner protected file retained inherited ACL state'
    }}

    $initialAttributes = [TicketboxTestRestorePrivilege]::GetAttributes()
    if ($initialAttributes -lt 0) {{
        foreach ($probe in @('directory', 'file')) {{
            $failedAsExpected = $false
            try {{
                if ($probe -eq 'directory') {{
                    Initialize-TicketboxProtectedDirectoryAtomically `
                        -Path '{_ps_literal(missing_directory)}' `
                        -FullControlAccounts $systemAccounts `
                        -OwnerAccount 'SYSTEM' | Out-Null
                }}
                else {{
                    Initialize-TicketboxProtectedDirectoryAtomically `
                        -Path '{_ps_literal(missing_file_parent)}' `
                        -FullControlAccounts @($currentAccount) `
                        -OwnerAccount $currentAccount | Out-Null
                    Write-TicketboxProtectedUtf8FileDurable `
                        -Path '{_ps_literal(missing_file_parent / "system.txt")}' `
                        -Text 'must-not-exist' `
                        -FullControlAccounts $systemAccounts `
                        -OwnerAccount 'SYSTEM'
                }}
            }}
            catch {{
                if ($_.Exception.Message -notlike 'Windows 未授予创建受保护对象所需的 SeRestorePrivilege：*') {{
                    throw
                }}
                $failedAsExpected = $true
            }}
            if (-not $failedAsExpected) {{ throw "$probe probe did not fail closed" }}
        }}
        if (Test-Path -LiteralPath '{_ps_literal(missing_directory)}') {{
            throw 'foreign-owner directory survived fail-closed path'
        }}
        if (Test-Path -LiteralPath '{_ps_literal(missing_file_parent / "system.txt")}') {{
            throw 'foreign-owner file survived fail-closed path'
        }}
        Write-Output 'MODE=privilege-missing-failed-closed'
        exit 0
    }}

    [TicketboxTestRestorePrivilege]::Disable()
    if ([TicketboxTestRestorePrivilege]::GetAttributes() -ne 0) {{
        throw 'test precondition did not disable SeRestorePrivilege'
    }}
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path '{_ps_literal(system_root)}' `
        -FullControlAccounts $systemAccounts `
        -OwnerAccount 'SYSTEM' | Out-Null
    if ([TicketboxTestRestorePrivilege]::GetAttributes() -ne 0) {{
        throw 'directory creation leaked SeRestorePrivilege enabled state'
    }}
    Write-TicketboxProtectedUtf8FileDurable `
        -Path '{_ps_literal(system_root / "system.txt")}' `
        -Text 'system-owner' `
        -FullControlAccounts $systemAccounts `
        -OwnerAccount 'SYSTEM'
    if ([TicketboxTestRestorePrivilege]::GetAttributes() -ne 0) {{
        throw 'file creation leaked SeRestorePrivilege enabled state'
    }}
    Set-TicketboxExactFileAcl `
        -Path '{_ps_literal(system_root / "system.txt")}' `
        -Accounts $systemAccounts `
        -OwnerAccount 'SYSTEM'
    Set-TicketboxExactDirectoryAcl `
        -Path '{_ps_literal(system_root)}' `
        -Accounts $systemAccounts `
        -OwnerAccount 'SYSTEM' `
        -Recurse
    Set-TicketboxExactFileAcl `
        -Path '{_ps_literal(system_root / "system.txt")}' `
        -Accounts $systemAccounts `
        -OwnerAccount 'SYSTEM'
    if ([TicketboxTestRestorePrivilege]::GetAttributes() -ne 0) {{
        throw 'existing SYSTEM-owned ACL update changed SeRestorePrivilege state'
    }}

    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path '{_ps_literal(bootstrap_root)}' `
        -FullControlAccounts $systemAccounts `
        -OwnerAccount 'SYSTEM' | Out-Null
    $script:DataRoot = '{_ps_literal(bootstrap_root)}'
    $script:AppData = Join-Path $script:DataRoot 'app'
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $script:AppData `
        -FullControlAccounts $systemAccounts `
        -OwnerAccount 'SYSTEM' | Out-Null
    Invoke-TicketboxIcaclsChecked $script:AppData @('/reset')
    $script:PostgresBootstrapAclAccounts = $systemAccounts
    $script:PostgresBootstrapAclOwnerAccount = 'SYSTEM'
    $script:SecretByteCount = 32
    $bootstrapState = New-PostgresBootstrapRecoveryState
    $bootstrapPath = Get-PostgresBootstrapRecoveryPath
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $bootstrapPath `
        -Text (ConvertTo-PostgresBootstrapRecoveryPayload $bootstrapState) `
        -FullControlAccounts $systemAccounts `
        -OwnerAccount 'SYSTEM'
    Invoke-TicketboxIcaclsChecked $bootstrapPath @('/reset')
    $bootstrapBeforeBytes = [IO.File]::ReadAllBytes($bootstrapPath)
    if (-not (Repair-PostgresBootstrapRecoveryFileAcl)) {{
        throw 'SYSTEM-owned inherited bootstrap ACL was not repaired'
    }}
    $bootstrapAcl = Get-TicketboxPathAcl $bootstrapPath
    if ($bootstrapAcl.Owner -cne 'S-1-5-18' -or
        -not $bootstrapAcl.AreAccessRulesProtected -or
        @($bootstrapAcl.Access | Where-Object {{ $_.IsInherited }}).Count -ne 0 -or
        -not (Test-TicketboxWindowsByteArrayEquals `
            $bootstrapBeforeBytes `
            ([IO.File]::ReadAllBytes($bootstrapPath)))) {{
        throw 'SYSTEM-owned bootstrap repair changed owner, ACL, or bytes'
    }}
    if ([TicketboxTestRestorePrivilege]::GetAttributes() -ne 0) {{
        throw 'SYSTEM-owned bootstrap repair changed SeRestorePrivilege state'
    }}
    $systemSid = 'S-1-5-18'
    foreach ($path in @('{_ps_literal(system_root)}', '{_ps_literal(system_root / "system.txt")}')) {{
        $acl = Get-TicketboxPathAcl $path
        if ($acl.Owner -cne $systemSid) {{
            throw "foreign-owner primitive did not persist SYSTEM owner: $path"
        }}
        if (-not $acl.AreAccessRulesProtected -or
            @($acl.Access | Where-Object {{ $_.IsInherited }}).Count -ne 0) {{
            throw "foreign-owner primitive retained inherited ACL state: $path"
        }}
    }}
    Write-Output 'MODE=privilege-present-enabled-and-restored'
}}
finally {{
    foreach ($path in @(
        '{_ps_literal(system_root)}',
        '{_ps_literal(bootstrap_root)}',
        '{_ps_literal(missing_file_parent)}',
        '{_ps_literal(current_root)}'
    )) {{
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }}
}}
""",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if "MODE=privilege-missing-failed-closed" in result.stdout:
        pytest.skip("current token does not contain SeRestorePrivilege")
    assert "MODE=privilege-present-enabled-and-restored" in result.stdout, result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows NTFS ACL contract")
def test_data_root_marker_retry_repairs_only_exact_inherited_shape(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"marker-retry-{index}.ps1"
        install_dir = tmp_path / f"install-{index}"
        protected_root = tmp_path / f"protected-root-{index}"
        recoverable_root = tmp_path / f"recoverable-root-{index}"
        foreign_rule_root = tmp_path / f"foreign-rule-root-{index}"
        untrusted_root = tmp_path / f"untrusted-root-{index}"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SAFETY)}'
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$accounts = @($account)
$encoding = [Text.UTF8Encoding]::new($false)

# This behavior test exercises the real ACL and marker chain in a pytest-owned
# profile path.  The production domain validator is covered separately and
# intentionally rejects profile paths as deployable DataRoots.
function Assert-TicketboxDataRootDomain {{
    param([string]$DataRoot, [string]$InstallDir)
    return ConvertTo-TicketboxWin32CanonicalPath $DataRoot
}}

function Write-InheritedMarker([string]$Root) {{
    $volume = Get-TicketboxVolumeIdentityForPath $Root
    $text = Get-TicketboxDataRootMarkerText `
        -DataRoot $Root `
        -InstallDir '{_ps_literal(install_dir)}' `
        -DataVolumeIdentity $volume
    [IO.File]::WriteAllText(
        (Get-TicketboxDataRootMarkerPath $Root),
        $text,
        $encoding)
}}

function Get-AclShape([string]$Path) {{
    $acl = Get-TicketboxPathAcl $Path
    $rules = @($acl.Access | ForEach-Object {{
        [string]::Join(':', @(
            $_.IdentityReference.Value,
            [string]$_.AccessControlType,
            [string][int]$_.FileSystemRights,
            [string]$_.InheritanceFlags,
            [string]$_.PropagationFlags,
            [string]$_.IsInherited
        ))
    }} | Sort-Object)
    return [string]::Join('|', @(
        $acl.Owner,
        [string]$acl.AreAccessRulesProtected,
        ($rules -join ',')
    ))
}}

Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{_ps_literal(protected_root)}' `
    -FullControlAccounts $accounts `
    -OwnerAccount $account | Out-Null
Write-TicketboxDataRootMarker `
    -DataRoot '{_ps_literal(protected_root)}' `
    -InstallDir '{_ps_literal(install_dir)}' `
    -FullControlAccounts $accounts `
    -OwnerAccount $account
$protectedMarker = Get-TicketboxDataRootMarkerPath '{_ps_literal(protected_root)}'
$protectedTextBefore = [Convert]::ToBase64String([IO.File]::ReadAllBytes($protectedMarker))
$protectedWriteTimeBefore = (Get-Item -LiteralPath $protectedMarker -Force).LastWriteTimeUtc.Ticks
Initialize-TicketboxSecureDataRoot `
    -DataRoot '{_ps_literal(protected_root)}' `
    -InstallDir '{_ps_literal(install_dir)}' `
    -Accounts $accounts `
    -OwnerAccount $account
Initialize-TicketboxSecureDataRoot `
    -DataRoot '{_ps_literal(protected_root)}' `
    -InstallDir '{_ps_literal(install_dir)}' `
    -Accounts $accounts `
    -OwnerAccount $account
$protectedAcl = Get-TicketboxPathAcl $protectedMarker
if (-not $protectedAcl.AreAccessRulesProtected -or
    @($protectedAcl.Access | Where-Object {{ $_.IsInherited }}).Count -ne 0 -or
    [Convert]::ToBase64String([IO.File]::ReadAllBytes($protectedMarker)) -cne
        $protectedTextBefore -or
    (Get-Item -LiteralPath $protectedMarker -Force).LastWriteTimeUtc.Ticks -ne
        $protectedWriteTimeBefore) {{
    throw 'normal protected marker was rewritten or left inheriting on retry'
}}

Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{_ps_literal(recoverable_root)}' `
    -FullControlAccounts $accounts `
    -OwnerAccount $account | Out-Null
Write-InheritedMarker '{_ps_literal(recoverable_root)}'
$recoverableMarker = Get-TicketboxDataRootMarkerPath '{_ps_literal(recoverable_root)}'
$before = Get-TicketboxPathAcl $recoverableMarker
if ($before.AreAccessRulesProtected -or
    @($before.Access | Where-Object {{ $_.IsInherited }}).Count -eq 0) {{
    throw 'test did not create the inheritance-only retry shape'
}}
Repair-TicketboxRecoverableDataRootMarkerAcl `
    -DataRoot '{_ps_literal(recoverable_root)}' `
    -InstallDir '{_ps_literal(install_dir)}' `
    -FullControlAccounts $accounts `
    -OwnerAccount $account
Repair-TicketboxRecoverableDataRootMarkerAcl `
    -DataRoot '{_ps_literal(recoverable_root)}' `
    -InstallDir '{_ps_literal(install_dir)}' `
    -FullControlAccounts $accounts `
    -OwnerAccount $account
$after = Get-TicketboxPathAcl $recoverableMarker
if (-not $after.AreAccessRulesProtected -or
    $after.Owner -cne $ownerSid -or
    @($after.Access | Where-Object {{ $_.IsInherited }}).Count -ne 0) {{
    throw 'exact inheritance-only retry shape was not normalized'
}}
Assert-TicketboxDataRootMarker `
    -DataRoot '{_ps_literal(recoverable_root)}' `
    -InstallDir '{_ps_literal(install_dir)}'

Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{_ps_literal(foreign_rule_root)}' `
    -FullControlAccounts $accounts `
    -OwnerAccount $account | Out-Null
Write-InheritedMarker '{_ps_literal(foreign_rule_root)}'
$foreignMarker = Get-TicketboxDataRootMarkerPath '{_ps_literal(foreign_rule_root)}'
Invoke-TicketboxIcaclsChecked $foreignMarker @('/grant', '*S-1-1-0:R')
$foreignBefore = Get-AclShape $foreignMarker
$foreignRejected = $false
try {{
    Repair-TicketboxRecoverableDataRootMarkerAcl `
        -DataRoot '{_ps_literal(foreign_rule_root)}' `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts $accounts `
        -OwnerAccount $account
}}
catch {{ $foreignRejected = $true }}
$foreignAfter = Get-AclShape $foreignMarker
if (-not $foreignRejected -or $foreignAfter -cne $foreignBefore) {{
    throw 'foreign explicit ACE was adopted or mutated'
}}

[IO.Directory]::CreateDirectory('{_ps_literal(untrusted_root)}') | Out-Null
Write-InheritedMarker '{_ps_literal(untrusted_root)}'
$untrustedMarker = Get-TicketboxDataRootMarkerPath '{_ps_literal(untrusted_root)}'
$untrustedBefore = Get-AclShape $untrustedMarker
$untrustedRejected = $false
try {{
    Repair-TicketboxRecoverableDataRootMarkerAcl `
        -DataRoot '{_ps_literal(untrusted_root)}' `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts $accounts `
        -OwnerAccount $account
}}
catch {{ $untrustedRejected = $true }}
$untrustedAfter = Get-AclShape $untrustedMarker
if (-not $untrustedRejected -or $untrustedAfter -cne $untrustedBefore) {{
    throw 'ordinary pre-existing directory was adopted or mutated'
}}
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
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
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows NTFS ACL contract")
def test_protected_data_root_marker_allows_only_exact_backend_rx_cross_engine(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"marker-backend-rx-{index}.ps1"
        install_dir = tmp_path / f"marker-backend-rx-install-{index}"
        case_root = tmp_path / f"marker-backend-rx-cases-{index}"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SERVICE_LIFECYCLE)}'
. '{_ps_literal(SAFETY)}'
. '{_ps_literal(DATABASE_SAFETY)}'
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
# Use built-in, SID-enabled services so this real NTFS test remains portable
# without creating or mutating an SCM service as part of the pytest process.
$backendServiceName = 'TrustedInstaller'
$wrongServiceName = 'Schedule'
$backendSid = Get-TicketboxServiceSid $backendServiceName
$wrongSid = Get-TicketboxServiceSid $wrongServiceName

# This behavior test exercises the real ACL and marker chain in a pytest-owned
# profile path.  The production domain validator is covered separately.
function Assert-TicketboxDataRootDomain {{
    param([string]$DataRoot, [string]$InstallDir)
    return ConvertTo-TicketboxWin32CanonicalPath $DataRoot
}}

function Get-AclShape([string]$Path) {{
    $acl = Get-TicketboxPathAcl $Path
    $rules = @($acl.Access | ForEach-Object {{
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
    }} | Sort-Object)
    return [string]::Join('|', @(
        $acl.Owner,
        [string]$acl.AreAccessRulesProtected,
        ($rules -join ',')
    ))
}}

function Get-MarkerSnapshot([string]$Path) {{
    return [pscustomobject]@{{
        Bytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes($Path))
        Acl = Get-AclShape $Path
        WriteTicks = (Get-Item -LiteralPath $Path -Force).LastWriteTimeUtc.Ticks
    }}
}}

function Assert-MarkerSnapshot([string]$Path, [object]$Before, [string]$Label) {{
    $after = Get-MarkerSnapshot $Path
    if (
        $after.Bytes -cne $Before.Bytes -or
        $after.Acl -cne $Before.Acl -or
        $after.WriteTicks -ne $Before.WriteTicks
    ) {{
        throw "$Label mutated marker bytes, ACL, or write time"
    }}
}}

function New-TestMarker([string]$Root) {{
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $Root `
        -FullControlAccounts @($account) `
        -OwnerAccount $account | Out-Null
    Write-TicketboxDataRootMarker `
        -DataRoot $Root `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts @($account) `
        -OwnerAccount $account
    return Get-TicketboxDataRootMarkerPath $Root
}}

[IO.Directory]::CreateDirectory('{_ps_literal(case_root)}') | Out-Null
[IO.Directory]::CreateDirectory('{_ps_literal(install_dir)}') | Out-Null

$privilegedRoot = Join-Path '{_ps_literal(case_root)}' 'privileged'
$privilegedMarker = New-TestMarker $privilegedRoot
$privilegedBefore = Get-MarkerSnapshot $privilegedMarker
Read-TicketboxProtectedDataRootMarker `
    -DataRoot $privilegedRoot `
    -InstallDir '{_ps_literal(install_dir)}' `
    -FullControlAccounts @($account) `
    -AclPhase backend_read_optional `
    -ExpectedBackendServiceName $backendServiceName `
    -OwnerAccount $account | Out-Null
$requiredMissingRejected = $false
try {{
    Read-TicketboxProtectedDataRootMarker `
        -DataRoot $privilegedRoot `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts @($account) `
        -AclPhase backend_read_required `
        -ExpectedBackendServiceName $backendServiceName `
        -OwnerAccount $account | Out-Null
}}
catch {{ $requiredMissingRejected = $true }}
if (-not $requiredMissingRejected) {{ throw 'required backend RX accepted a missing ACE' }}
Assert-MarkerSnapshot $privilegedMarker $privilegedBefore 'privileged optional/required reads'

$backendRoot = Join-Path '{_ps_literal(case_root)}' 'backend-rx'
$backendMarker = New-TestMarker $backendRoot
Set-TicketboxExactFileAcl `
    -Path $backendMarker `
    -Accounts @($account) `
    -ReadExecuteAccounts @($backendSid) `
    -OwnerAccount $account
$backendBefore = Get-MarkerSnapshot $backendMarker
foreach ($phase in @('backend_read_optional', 'backend_read_required')) {{
    Read-TicketboxProtectedDataRootMarker `
        -DataRoot $backendRoot `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts @($account) `
        -AclPhase $phase `
        -ExpectedBackendServiceName $backendServiceName `
        -OwnerAccount $account | Out-Null
}}
$unboundRejected = $false
try {{
    Read-TicketboxProtectedDataRootMarker `
        -DataRoot $backendRoot `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts @($account) `
        -OwnerAccount $account | Out-Null
}}
catch {{ $unboundRejected = $true }}
if (-not $unboundRejected) {{ throw 'generic marker reader silently accepted backend RX' }}
Assert-MarkerSnapshot $backendMarker $backendBefore 'exact backend RX reads'

$wrongRoot = Join-Path '{_ps_literal(case_root)}' 'wrong-rx'
$wrongMarker = New-TestMarker $wrongRoot
Set-TicketboxExactFileAcl `
    -Path $wrongMarker `
    -Accounts @($account) `
    -ReadExecuteAccounts @($wrongSid) `
    -OwnerAccount $account
$wrongBefore = Get-MarkerSnapshot $wrongMarker
$wrongRejected = $false
try {{
    Read-TicketboxProtectedDataRootMarker `
        -DataRoot $wrongRoot `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts @($account) `
        -AclPhase backend_read_optional `
        -ExpectedBackendServiceName $backendServiceName `
        -OwnerAccount $account | Out-Null
}}
catch {{ $wrongRejected = $true }}
if (-not $wrongRejected) {{ throw 'wrong service SID RX was accepted' }}
Assert-MarkerSnapshot $wrongMarker $wrongBefore 'wrong service SID rejection'

$writeRoot = Join-Path '{_ps_literal(case_root)}' 'backend-modify'
$writeMarker = New-TestMarker $writeRoot
Invoke-TicketboxIcaclsChecked $writeMarker @('/grant:r', "*$backendSid`:M")
$writeBefore = Get-MarkerSnapshot $writeMarker
$writeRejected = $false
try {{
    Read-TicketboxProtectedDataRootMarker `
        -DataRoot $writeRoot `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts @($account) `
        -AclPhase backend_read_optional `
        -ExpectedBackendServiceName $backendServiceName `
        -OwnerAccount $account | Out-Null
}}
catch {{ $writeRejected = $true }}
if (-not $writeRejected) {{ throw 'write-capable backend ACE was accepted' }}
Assert-MarkerSnapshot $writeMarker $writeBefore 'write-capable backend rejection'

$extraRoot = Join-Path '{_ps_literal(case_root)}' 'backend-extra-rx'
$extraMarker = New-TestMarker $extraRoot
Set-TicketboxExactFileAcl `
    -Path $extraMarker `
    -Accounts @($account) `
    -ReadExecuteAccounts @($backendSid) `
    -OwnerAccount $account
Invoke-TicketboxIcaclsChecked $extraMarker @('/grant', "*$wrongSid`:RX")
$extraBefore = Get-MarkerSnapshot $extraMarker
$extraRejected = $false
try {{
    Read-TicketboxProtectedDataRootMarker `
        -DataRoot $extraRoot `
        -InstallDir '{_ps_literal(install_dir)}' `
        -FullControlAccounts @($account) `
        -AclPhase backend_read_optional `
        -ExpectedBackendServiceName $backendServiceName `
        -OwnerAccount $account | Out-Null
}}
catch {{ $extraRejected = $true }}
if (-not $extraRejected) {{ throw 'expected backend RX plus extra RX was accepted' }}
Assert-MarkerSnapshot $extraMarker $extraBefore 'extra service SID rejection'
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
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
            timeout=45,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows NTFS ACL contract")
def test_installation_identity_retry_repairs_only_exact_bound_inherited_shape(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        accepted_root = tmp_path / f"identity-accepted-{index}"
        rejected_root = tmp_path / f"identity-rejected-{index}"
        install_dir = tmp_path / f"install-{index}"
        harness = tmp_path / f"identity-retry-{index}.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SAFETY)}'
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxPersistentInstallationIdentityAclAccounts = @($account)
$script:TicketboxPersistentInstallationIdentityOwnerAccount = $account
$encoding = [Text.UTF8Encoding]::new($false)

function New-Candidate([string]$Root, [string]$InstallDir) {{
    return [pscustomobject][ordered]@{{
        BackendVersionFloor = '1.2.0'
        BuildManifestSha256 = ('A' * 64)
        DataRoot = [IO.Path]::GetFullPath($Root)
        InstallDir = [IO.Path]::GetFullPath($InstallDir)
        PgServiceName = 'TicketboxPg'
        BackendServiceName = 'TicketboxBackend'
        PgPort = 5440
        BackendPort = 8001
        MaintenanceHelperRelativePath = 'ticketbox-database-maintenance.exe'
        MaintenanceHelperSize = [int64]123
        MaintenanceHelperSha256 = ('B' * 64)
        DatabaseGenerationProgramRelativePath =
            'DATABASE_GENERATION_PROGRAM.json'
        DatabaseGenerationProgramSize = [int64]456
        DatabaseGenerationProgramSha256 = ('C' * 64)
    }}
}}

foreach ($root in @('{_ps_literal(accepted_root)}', '{_ps_literal(rejected_root)}')) {{
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $root `
        -FullControlAccounts @($account) `
        -OwnerAccount $account | Out-Null
}}

$acceptedCandidate = New-Candidate `
    '{_ps_literal(accepted_root)}' `
    '{_ps_literal(install_dir)}'
$acceptedPath = Get-TicketboxPendingInstallationIdentityPath `
    '{_ps_literal(accepted_root)}'
$acceptedText = Get-TicketboxPersistentInstallationIdentityText `
    -State 'PENDING' `
    -OperationId ([guid]::NewGuid().ToString('D')) `
    -InstallationId ([guid]::NewGuid().ToString('D')) `
    -Candidate $acceptedCandidate
[IO.File]::WriteAllText($acceptedPath, $acceptedText, $encoding)
$beforeBytes = [IO.File]::ReadAllBytes($acceptedPath)
$beforeAcl = Get-TicketboxPathAcl $acceptedPath
if ($beforeAcl.AreAccessRulesProtected -or
    @($beforeAcl.Access | Where-Object {{ -not $_.IsInherited }}).Count -ne 0) {{
    throw 'accepted test precondition was not an exact inherited ACL'
}}
$changed = Repair-TicketboxRecoverableInstallationIdentityAcl `
    -Candidate $acceptedCandidate `
    -Pending
if (-not $changed) {{ throw 'exact inherited identity was not repaired' }}
$afterBytes = [IO.File]::ReadAllBytes($acceptedPath)
if (-not (Test-TicketboxWindowsByteArrayEquals $beforeBytes $afterBytes)) {{
    throw 'identity ACL repair changed protected bytes'
}}
$accepted = Read-TicketboxPersistentInstallationIdentity `
    -DataRoot '{_ps_literal(accepted_root)}' `
    -Pending
if ($accepted.State -cne 'PENDING' -or
    $accepted.BuildManifestSha256 -cne ('A' * 64)) {{
    throw 'repaired identity did not preserve canonical binding'
}}
if (Repair-TicketboxRecoverableInstallationIdentityAcl `
    -Candidate $acceptedCandidate `
    -Pending) {{
    throw 'already protected identity did not converge idempotently'
}}

$identityCandidate = New-Candidate `
    '{_ps_literal(rejected_root)}' `
    '{_ps_literal(install_dir)}'
$rejectedPath = Get-TicketboxPendingInstallationIdentityPath `
    '{_ps_literal(rejected_root)}'
$rejectedText = Get-TicketboxPersistentInstallationIdentityText `
    -State 'PENDING' `
    -OperationId ([guid]::NewGuid().ToString('D')) `
    -InstallationId ([guid]::NewGuid().ToString('D')) `
    -Candidate $identityCandidate
[IO.File]::WriteAllText($rejectedPath, $rejectedText, $encoding)
$rejectedBytes = [IO.File]::ReadAllBytes($rejectedPath)
$mismatchedCandidate = New-Candidate `
    '{_ps_literal(rejected_root)}' `
    '{_ps_literal(tmp_path / "different-install")}'
$rejected = $false
try {{
    Repair-TicketboxRecoverableInstallationIdentityAcl `
        -Candidate $mismatchedCandidate `
        -Pending | Out-Null
}}
catch {{ $rejected = $true }}
$rejectedAcl = Get-TicketboxPathAcl $rejectedPath
if (-not $rejected -or
    $rejectedAcl.AreAccessRulesProtected -or
    @($rejectedAcl.Access | Where-Object {{ -not $_.IsInherited }}).Count -ne 0 -or
    -not (Test-TicketboxWindowsByteArrayEquals `
        $rejectedBytes `
        ([IO.File]::ReadAllBytes($rejectedPath)))) {{
    throw 'mismatched inherited identity was mutated or accepted'
}}
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
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
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
