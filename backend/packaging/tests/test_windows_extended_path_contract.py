"""Windows extended-length path contracts for native packaging I/O."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
SAFETY_SCRIPT = PACKAGING / "windows_installation_safety.ps1"


def _ps_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _run_harness(engine: str, harness: Path) -> None:
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
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path namespace contract")
def test_extended_path_normalizer_is_idempotent_and_rejects_ambiguous_names(
    tmp_path: Path,
) -> None:
    script = r"""
$ErrorActionPreference = 'Stop'
. '@SAFETY@'

$cases = @(
    [pscustomobject]@{
        Input = 'C:\release\file.json'
        Expected = '\\?\C:\release\file.json'
    },
    [pscustomobject]@{
        Input = '\\?\C:\release\file.json'
        Expected = '\\?\C:\release\file.json'
    },
    [pscustomobject]@{
        Input = '\\server\share\folder\file.json'
        Expected = '\\?\UNC\server\share\folder\file.json'
    },
    [pscustomobject]@{
        Input = '\\?\UNC\server\share\folder\file.json'
        Expected = '\\?\UNC\server\share\folder\file.json'
    }
)
foreach ($case in $cases) {
    $actual = ConvertTo-TicketboxWin32ExtendedPath $case.Input
    if ($actual -cne $case.Expected) {
        throw "unexpected normalized path: $($case.Input) -> $actual"
    }
}

$invalidPaths = @(
    'relative\file.json',
    'C:relative\file.json',
    '\rooted\file.json',
    '\\.\PhysicalDrive0',
    '\??\C:\release\file.json',
    '\\?\GLOBALROOT\Device\HarddiskVolume1\file.json',
    '\\?\Volume{11111111-1111-1111-1111-111111111111}\file.json',
    'C:\release\..\file.json',
    'C:\release\file.',
    'C:\release\NUL.txt',
    '\\server',
    '\\?\C:/release/file.json'
)
foreach ($invalidPath in $invalidPaths) {
    $rejected = $false
    try {
        ConvertTo-TicketboxWin32ExtendedPath $invalidPath | Out-Null
    }
    catch {
        $rejected = $true
    }
    if (-not $rejected) {
        throw "ambiguous or non-file path was accepted: $invalidPath"
    }
}
""".replace("@SAFETY@", _ps_literal(SAFETY_SCRIPT))

    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"extended-path-normalizer-{index}.ps1"
        harness.write_text(script, encoding="utf-8-sig")
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path namespace contract")
def test_durable_and_exact_native_io_supports_real_extended_length_path(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        case_root = tmp_path / f"native-long-path-{index}"
        parent = case_root
        while len(str(parent)) < 185:
            parent /= f"segment-{len(parent.parts):02d}-abcdefghij"
        parent.mkdir(parents=True)

        destination = parent / f"operation-{'x' * 100}-evidence.json"
        replacement = case_root / "replacement.json"
        backup = case_root / "backup.json"
        delete_leaf_length = 275 - len(str(case_root)) - 1
        delete_root = case_root / f"delete-{'d' * (delete_leaf_length - 7)}"
        extended_delete_root = rf"\\?\{delete_root}"
        os.mkdir(extended_delete_root)
        with open(
            os.path.join(extended_delete_root, "sentinel.txt"),
            "w",
            encoding="utf-8",
        ) as sentinel:
            sentinel.write("delete me")
        replacement.write_text("replacement", encoding="utf-8")
        assert len(str(destination)) > 260
        assert len(str(delete_root)) > 260
        assert len(destination.name) <= 255

        harness = tmp_path / f"extended-native-io-{index}.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SAFETY_SCRIPT)}'

$destination = '{_ps_literal(destination)}'
$replacement = '{_ps_literal(replacement)}'
$backup = '{_ps_literal(backup)}'
$deleteRoot = '{_ps_literal(delete_root)}'
Write-TicketboxUtf8FileDurable -Path $destination -Text 'source'
if ((Get-TicketboxPathEntryKindNoFollow $destination) -cne 'File') {{
    throw 'long destination was not visible through exact no-follow inspection'
}}
Initialize-TicketboxExactTreeDeleteNativeMethods
if ([TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
    $destination,
    4096
) -cne 'source') {{
    throw 'exact native read returned the wrong initial content'
}}

$replaceResult = Replace-TicketboxFileDurablePreservingMetadata `
    -Replacement $replacement `
    -Destination $destination `
    -Backup $backup
if (-not $replaceResult.Succeeded) {{
    throw "ReplaceFileW failed with Win32=$($replaceResult.NativeErrorCode)"
}}
if ([TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
    $destination,
    4096
) -cne 'replacement') {{
    throw 'exact native read returned the wrong replacement content'
}}
Remove-TicketboxTreeExact -Path $deleteRoot
if ((Get-TicketboxPathEntryKindNoFollow $deleteRoot) -cne 'Missing') {{
    throw 'long exact-delete root remained after wrapper completion'
}}
""",
            encoding="utf-8-sig",
        )
        _run_harness(engine, harness)

        assert backup.read_text(encoding="utf-8") == "source"
        assert not replacement.exists()
        assert not os.path.exists(extended_delete_root)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path namespace contract")
def test_exact_tree_public_entries_fail_closed_before_native_io(tmp_path: Path) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        case_root = tmp_path / f"exact-public-paths-{index}"
        case_root.mkdir()
        victim = case_root / "victim.txt"
        victim.write_text("victim", encoding="utf-8")
        delete_victim = case_root / "delete-victim"
        delete_victim.mkdir()
        (delete_victim / "sentinel.txt").write_text("keep", encoding="utf-8")
        coordination_artifact = case_root / "coordination.tmp"
        coordination_artifact.write_text("keep", encoding="utf-8")
        legacy_source = case_root / "legacy.txt"
        legacy_source.write_text("legacy", encoding="utf-8")
        new_directory = case_root / "new-directory"

        script = r"""
$ErrorActionPreference = 'Stop'
. '@SAFETY@'
Initialize-TicketboxExactTreeDeleteNativeMethods

function Assert-ArgumentRejected([scriptblock]$Action, [string]$Label) {
    $rejected = $false
    try {
        & $Action | Out-Null
    }
    catch {
        $baseException = $_.Exception.GetBaseException()
        if ($baseException -isnot [ArgumentException]) {
            throw "$Label failed after native I/O instead of strict validation: $($baseException.Message)"
        }
        $rejected = $true
    }
    if (-not $rejected) {
        throw "$Label unexpectedly accepted a non-canonical public path"
    }
}

$root = '@ROOT@'
$extendedRoot = '\\?\' + $root
$extendedVictim = '\\?\' + '@VICTIM@'
$extendedDeleteVictim = '\\?\' + '@DELETE_VICTIM@'
$coordinationArtifact = '@COORDINATION_ARTIFACT@'
$legacySource = '@LEGACY_SOURCE@'
$newDirectory = '@NEW_DIRECTORY@'
$invalidFilePaths = @(
    "$extendedRoot\pivot\..\victim.txt",
    "$extendedVictim.",
    "$extendedRoot\NUL",
    '\\?\GLOBALROOT\Device\HarddiskVolume1\ticketbox-invalid',
    '\\?\Volume{11111111-1111-1111-1111-111111111111}\ticketbox-invalid'
)
foreach ($candidate in $invalidFilePaths) {
    Assert-ArgumentRejected `
        -Label "InspectEntry $candidate" `
        -Action { [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($candidate) }
    Assert-ArgumentRejected `
        -Label "GetDirectoryIdentity $candidate" `
        -Action { [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($candidate) }
    Assert-ArgumentRejected `
        -Label "ReadExactUtf8File $candidate" `
        -Action { [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File($candidate, 4096) }
    Assert-ArgumentRejected `
        -Label "Get-TicketboxPathEntryKindNoFollow $candidate" `
        -Action { Get-TicketboxPathEntryKindNoFollow $candidate }
    Assert-ArgumentRejected `
        -Label "Get-TicketboxVolumeIdentityForPath $candidate" `
        -Action { Get-TicketboxVolumeIdentityForPath $candidate }
}

$invalidRootPaths = @(
    "$extendedRoot\pivot\..\delete-victim",
    "$extendedDeleteVictim.",
    "$extendedRoot\NUL",
    '\\?\GLOBALROOT\Device\HarddiskVolume1\ticketbox-invalid',
    '\\?\Volume{11111111-1111-1111-1111-111111111111}\ticketbox-invalid'
)
foreach ($candidate in $invalidRootPaths) {
    Assert-ArgumentRejected `
        -Label "DeleteTree $candidate" `
        -Action {
            [TicketboxExactTreeDeleteNativeMethods]::DeleteTree(
                $candidate,
                '',
                [Action]$null
            )
        }
    Assert-ArgumentRejected `
        -Label "Remove-TicketboxTreeExact $candidate" `
        -Action { Remove-TicketboxTreeExact $candidate }
}

$invalidFileAlias = $invalidFilePaths[0]
$invalidTrailingFile = $invalidFilePaths[1]
$invalidDirectoryAlias = $invalidRootPaths[0]
$invalidTrailingDirectory = $invalidRootPaths[1]
$invalidNewDirectory = "$extendedRoot\pivot\..\new-directory"
$validReadyPath = Join-Path $root 'ready.txt'
$validReleasePath = Join-Path $root 'release.txt'
$fileSecurity = New-Object System.Security.AccessControl.FileSecurity
$helperEvidence = [pscustomobject]@{
    RelativePath = 'ticketbox-database-maintenance.exe'
    Size = [int64]1
    Sha256 = ('0' * 64)
}

$statefulFileChecks = @(
    [pscustomobject]@{
        Label = 'Write-TicketboxUtf8FileDurable traversal'
        Action = { Write-TicketboxUtf8FileDurable -Path $invalidFileAlias -Text 'overwrite' -ReplaceExisting }
    },
    [pscustomobject]@{
        Label = 'Write-TicketboxUtf8FileDurable trailing dot'
        Action = { Write-TicketboxUtf8FileDurable -Path $invalidTrailingFile -Text 'overwrite' -ReplaceExisting }
    },
    [pscustomobject]@{
        Label = 'New-TicketboxProtectedFileStream traversal'
        Action = {
            $stream = New-TicketboxProtectedFileStream `
                -Path $invalidFileAlias `
                -Security $fileSecurity
            if ($null -ne $stream) { $stream.Dispose() }
        }
    },
    [pscustomobject]@{
        Label = 'Write-TicketboxProtectedUtf8FileDurable traversal'
        Action = {
            Write-TicketboxProtectedUtf8FileDurable `
                -Path $invalidFileAlias `
                -Text 'overwrite' `
                -FullControlAccounts @('SYSTEM') `
                -OwnerAccount 'SYSTEM' `
                -ReplaceExisting
        }
    },
    [pscustomobject]@{
        Label = 'Read-TicketboxProtectedUtf8Artifact traversal'
        Action = { Read-TicketboxProtectedUtf8Artifact -Path $invalidFileAlias }
    },
    [pscustomobject]@{
        Label = 'Remove-TicketboxProtectedUtf8Artifact trailing dot'
        Action = { Remove-TicketboxProtectedUtf8Artifact -Path $invalidTrailingFile }
    },
    [pscustomobject]@{
        Label = 'Sync-TicketboxFileDurable traversal'
        Action = { Sync-TicketboxFileDurable -Path $invalidFileAlias }
    },
    [pscustomobject]@{
        Label = 'Get-TicketboxPortableFileSha256 traversal'
        Action = { Get-TicketboxPortableFileSha256 -Path $invalidFileAlias }
    },
    [pscustomobject]@{
        Label = 'Read-TicketboxInstalledBuildManifest traversal'
        Action = { Read-TicketboxInstalledBuildManifest -Path $invalidFileAlias }
    },
    [pscustomobject]@{
        Label = 'Assert-TicketboxLegacyProtectedFileAcl traversal'
        Action = { Assert-TicketboxLegacyProtectedFileAcl -Path $invalidFileAlias }
    },
    [pscustomobject]@{
        Label = 'Open-TicketboxVerifiedDatabaseMaintenanceHelperLease traversal'
        Action = {
            $lease = Open-TicketboxVerifiedDatabaseMaintenanceHelperLease `
                -Path $invalidFileAlias `
                -ExpectedRelativePath 'ticketbox-database-maintenance.exe' `
                -ExpectedSize 1 `
                -ExpectedSha256 ('0' * 64)
            Close-TicketboxDatabaseMaintenanceHelperLease $lease
        }
    },
    [pscustomobject]@{
        Label = 'Read-TicketboxDataRootProvisioningIntent traversal'
        Action = { Read-TicketboxDataRootProvisioningIntent -Path $invalidFileAlias }
    }
)
foreach ($check in $statefulFileChecks) {
    Assert-ArgumentRejected -Label $check.Label -Action $check.Action
}

$statefulDirectoryChecks = @(
    [pscustomobject]@{
        Label = 'Enter-TicketboxDirectoryMutationGuard traversal'
        Action = {
            $guard = $null
            try { $guard = Enter-TicketboxDirectoryMutationGuard -Path $invalidDirectoryAlias }
            finally { if ($null -ne $guard) { $guard.Dispose() } }
        }
    },
    [pscustomobject]@{
        Label = 'Initialize-TicketboxProtectedDirectoryAtomically traversal'
        Action = {
            Initialize-TicketboxProtectedDirectoryAtomically `
                -Path $invalidNewDirectory `
                -FullControlAccounts @('SYSTEM') `
                -OwnerAccount 'SYSTEM'
        }
    },
    [pscustomobject]@{
        Label = 'Initialize-TicketboxInstallerStateDirectory trailing dot'
        Action = {
            Initialize-TicketboxInstallerStateDirectory `
                -Path $invalidTrailingDirectory `
                -FullControlAccounts @('SYSTEM') `
                -OwnerAccount 'SYSTEM'
        }
    },
    [pscustomobject]@{
        Label = 'Remove-TicketboxProtectedStagingArtifacts traversal'
        Action = { Remove-TicketboxProtectedStagingArtifacts -Path $invalidDirectoryAlias }
    },
    [pscustomobject]@{
        Label = 'Assert-TicketboxProtectedDirectoryAcl traversal'
        Action = { Assert-TicketboxProtectedDirectoryAcl -Path $invalidDirectoryAlias }
    },
    [pscustomobject]@{
        Label = 'Set-TicketboxExactDirectoryAcl traversal'
        Action = {
            Set-TicketboxExactDirectoryAcl `
                -Path $invalidDirectoryAlias `
                -Accounts @('SYSTEM')
        }
    },
    [pscustomobject]@{
        Label = 'Set-TicketboxExactDirectoryAclCore traversal'
        Action = {
            Set-TicketboxExactDirectoryAclCore `
                -Path $invalidDirectoryAlias `
                -Accounts @('SYSTEM')
        }
    },
    [pscustomobject]@{
        Label = 'Assert-NoTicketboxAncestorReparsePoints traversal'
        Action = { Assert-NoTicketboxAncestorReparsePoints -Path $invalidDirectoryAlias }
    },
    [pscustomobject]@{
        Label = 'Assert-NoTicketboxReparsePoints traversal'
        Action = { Assert-NoTicketboxReparsePoints -DataRoot $invalidDirectoryAlias }
    }
)
foreach ($check in $statefulDirectoryChecks) {
    Assert-ArgumentRejected -Label $check.Label -Action $check.Action
}

Assert-ArgumentRejected `
    -Label 'Move-TicketboxLegacyInstallerStateArtifact validates both raw paths' `
    -Action {
        Move-TicketboxLegacyInstallerStateArtifact `
            -LegacyPath $legacySource `
            -CurrentPath $invalidTrailingFile
    }
Assert-ArgumentRejected `
    -Label 'Remove-TicketboxDirectoryGuardCoordinationArtifacts validates all paths' `
    -Action {
        Remove-TicketboxDirectoryGuardCoordinationArtifacts `
            -ParentPath $root `
            -Paths @($coordinationArtifact, $invalidTrailingFile)
    }
Assert-ArgumentRejected `
    -Label 'Wait-TicketboxDirectoryMutationGuardLease validates DataRoot first' `
    -Action {
        Wait-TicketboxDirectoryMutationGuardLease `
            -Path $invalidDirectoryAlias `
            -InstallDir $root `
            -ReadyPath $validReadyPath `
            -ReleasePath $validReleasePath `
            -OwnerProcessId $PID `
            -OwnerIdentity ([pscustomobject]@{}) `
            -OnLeaseReady {}
    }
Assert-ArgumentRejected `
    -Label 'Wait-TicketboxDirectoryMutationGuardLease validates retain-lock before I/O' `
    -Action {
        Wait-TicketboxDirectoryMutationGuardLease `
            -Path $root `
            -InstallDir $root `
            -ReadyPath $validReadyPath `
            -ReleasePath $validReleasePath `
            -OwnerProcessId $PID `
            -OwnerIdentity ([pscustomobject]@{}) `
            -OnLeaseReady {} `
            -RetainWhileLockPath $invalidTrailingFile
    }
if (-not (Test-TicketboxExclusiveFileLockHeld -Path $invalidFileAlias)) {
    throw 'invalid exclusive-lock path was normalized into an unlocked file'
}

$authorityChecks = @(
    [pscustomobject]@{
        Label = 'ConvertTo-TicketboxCanonicalPath traversal'
        Action = { ConvertTo-TicketboxCanonicalPath $invalidDirectoryAlias }
    },
    [pscustomobject]@{
        Label = 'Get-TicketboxRuntimeDataBindingDirectory traversal'
        Action = { Get-TicketboxRuntimeDataBindingDirectory $invalidDirectoryAlias }
    },
    [pscustomobject]@{
        Label = 'Get-TicketboxRuntimeBootstrapRecoveryGuardPath traversal'
        Action = { Get-TicketboxRuntimeBootstrapRecoveryGuardPath $invalidDirectoryAlias }
    },
    [pscustomobject]@{
        Label = 'Get-TicketboxVolumeBoundDataRootPath traversal'
        Action = {
            Get-TicketboxVolumeBoundDataRootPath `
                -DataRoot $invalidDirectoryAlias `
                -DataVolumeIdentity '\\?\Volume{11111111-1111-1111-1111-111111111111}\'
        }
    },
    [pscustomobject]@{
        Label = 'Resolve-TicketboxInstalledDatabaseMaintenanceHelperPath traversal'
        Action = {
            Resolve-TicketboxInstalledDatabaseMaintenanceHelperPath `
                -InstallDir $invalidDirectoryAlias `
                -Evidence $helperEvidence
        }
    },
    [pscustomobject]@{
        Label = 'Get-TicketboxDataRootProvisioningIntentText validates InstallDir before volume I/O'
        Action = {
            Get-TicketboxDataRootProvisioningIntentText `
                -DataRoot $root `
                -InstallDir $invalidDirectoryAlias `
                -DataVolumeIdentity '\\?\Volume{11111111-1111-1111-1111-111111111111}\'
        }
    },
    [pscustomobject]@{
        Label = 'Read-TicketboxRuntimeDataBinding validates CommonApplicationData before marker I/O'
        Action = {
            Read-TicketboxRuntimeDataBinding `
                -DataRoot $root `
                -InstallDir $root `
                -ServiceReadExecuteAccounts @('SYSTEM') `
                -CommonApplicationData $invalidDirectoryAlias
        }
    },
    [pscustomobject]@{
        Label = 'Initialize-TicketboxRuntimeDataBinding validates CommonApplicationData before marker I/O'
        Action = {
            Initialize-TicketboxRuntimeDataBinding `
                -DataRoot $root `
                -InstallDir $root `
                -ServiceReadExecuteAccounts @('SYSTEM') `
                -CommonApplicationData $invalidDirectoryAlias
        }
    },
    [pscustomobject]@{
        Label = 'Remove-TicketboxRuntimeDataBinding validates DataRoot before early return'
        Action = {
            Remove-TicketboxRuntimeDataBinding `
                -DataRoot $invalidDirectoryAlias `
                -InstallDir $root `
                -ServiceReadExecuteAccounts @('SYSTEM') `
                -CommonApplicationData $root
        }
    },
    [pscustomobject]@{
        Label = 'Assert-TicketboxRegisteredDataRootBinding validates before registry read'
        Action = {
            Assert-TicketboxRegisteredDataRootBinding `
                -DataRoot $invalidDirectoryAlias `
                -RegistryReader { throw 'registry reader must not run' }
        }
    },
    [pscustomobject]@{
        Label = 'Read-TicketboxDataRootMarker validates InstallDir before marker I/O'
        Action = {
            Read-TicketboxDataRootMarker `
                -DataRoot $root `
                -InstallDir $invalidDirectoryAlias
        }
    },
    [pscustomobject]@{
        Label = 'Write-TicketboxDataRootMarker validates InstallDir before volume I/O'
        Action = {
            Write-TicketboxDataRootMarker `
                -DataRoot $root `
                -InstallDir $invalidDirectoryAlias
        }
    },
    [pscustomobject]@{
        Label = 'Assert-TicketboxDataRootMarkerInitialization validates InstallDir before marker I/O'
        Action = {
            Assert-TicketboxDataRootMarkerInitialization `
                -DataRoot $root `
                -InstallDir $invalidDirectoryAlias
        }
    },
    [pscustomobject]@{
        Label = 'Read-TicketboxProtectedDataRootMarker validates InstallDir before marker I/O'
        Action = {
            Read-TicketboxProtectedDataRootMarker `
                -DataRoot $root `
                -InstallDir $invalidDirectoryAlias
        }
    },
    [pscustomobject]@{
        Label = 'Assert-TicketboxLegacyPreservedDataLayout validates EnvPath before domain I/O'
        Action = {
            Assert-TicketboxLegacyPreservedDataLayout `
                -DataRoot $root `
                -InstallDir $root `
                -EnvPath $invalidFileAlias `
                -PgData $root `
                -ExpectedPgMajor 15
        }
    },
    [pscustomobject]@{
        Label = 'Assert-TicketboxDataRootDomain validates InstallDir before drive I/O'
        Action = {
            Assert-TicketboxDataRootDomain `
                -DataRoot $root `
                -InstallDir $invalidDirectoryAlias
        }
    },
    [pscustomobject]@{
        Label = 'Assert-TicketboxDataRootDeletionSafety validates registration before domain I/O'
        Action = {
            Assert-TicketboxDataRootDeletionSafety `
                -DataRoot $root `
                -RegisteredDataRoot $invalidDirectoryAlias `
                -InstallDir $root
        }
    }
)
foreach ($check in $authorityChecks) {
    Assert-ArgumentRejected -Label $check.Label -Action $check.Action
}

$unexpectedArtifacts = @(
    Get-ChildItem -LiteralPath $root -Force -Recurse |
        Where-Object { $_.Name -match '^\.ticketbox-(durable|protected)-.*\.tmp$' }
)
if ($unexpectedArtifacts.Count -ne 0) {
    throw 'strict wrapper validation created temporary artifacts before rejection'
}
if (-not [IO.File]::Exists('@VICTIM@') -or
    -not [IO.File]::Exists('@DELETE_SENTINEL@') -or
    -not [IO.File]::Exists($coordinationArtifact) -or
    -not [IO.File]::Exists($legacySource) -or
    [IO.Directory]::Exists($newDirectory) -or
    [IO.File]::ReadAllText('@VICTIM@') -cne 'victim') {
    throw 'strict public-path validation mutated its controlled victim'
}
"""
        script = (
            script.replace("@SAFETY@", _ps_literal(SAFETY_SCRIPT))
            .replace("@ROOT@", _ps_literal(case_root))
            .replace("@VICTIM@", _ps_literal(victim))
            .replace("@DELETE_VICTIM@", _ps_literal(delete_victim))
            .replace(
                "@COORDINATION_ARTIFACT@",
                _ps_literal(coordination_artifact),
            )
            .replace("@LEGACY_SOURCE@", _ps_literal(legacy_source))
            .replace("@NEW_DIRECTORY@", _ps_literal(new_directory))
            .replace(
                "@DELETE_SENTINEL@",
                _ps_literal(delete_victim / "sentinel.txt"),
            )
        )
        harness = tmp_path / f"exact-public-paths-{index}.ps1"
        harness.write_text(script, encoding="utf-8-sig")
        _run_harness(engine, harness)

        assert victim.read_text(encoding="utf-8") == "victim"
        assert (delete_victim / "sentinel.txt").read_text(encoding="utf-8") == "keep"
        assert coordination_artifact.read_text(encoding="utf-8") == "keep"
        assert legacy_source.read_text(encoding="utf-8") == "legacy"
        assert not new_directory.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path namespace contract")
def test_exact_tree_recursively_deletes_literal_hostile_children_and_defers_marker(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        case_root = tmp_path / f"exact-hostile-tree-{index}"
        case_root.mkdir()
        script = r"""
$ErrorActionPreference = 'Stop'
. '@SAFETY@'
Initialize-TicketboxExactTreeDeleteNativeMethods

$root = '@ROOT@'
$extendedRoot = ConvertTo-TicketboxWin32ExtendedPath $root
$markerLeaf = '.ticketbox-data-root.json'
$markerPath = Join-Path $root $markerLeaf
[IO.File]::WriteAllText($markerPath, 'marker', [Text.Encoding]::UTF8)
$hostileFiles = @(
    "$extendedRoot\NUL",
    "$extendedRoot\trailing.",
    "$extendedRoot\trailing "
)
foreach ($path in $hostileFiles) {
    [IO.File]::WriteAllText($path, 'hostile', [Text.Encoding]::UTF8)
}
$hostileDirectory = "$extendedRoot\AUX"
[IO.Directory]::CreateDirectory($hostileDirectory) | Out-Null
$nestedHostile = "$hostileDirectory\COM1"
[IO.File]::WriteAllText($nestedHostile, 'nested', [Text.Encoding]::UTF8)

$names = @([IO.Directory]::GetFileSystemEntries($extendedRoot) |
    ForEach-Object { [IO.Path]::GetFileName($_) })
foreach ($expectedName in @('NUL', 'trailing.', 'trailing ', 'AUX', $markerLeaf)) {
    if ($names -cnotcontains $expectedName) {
        throw "extended fixture lost literal child name: [$expectedName]"
    }
}

$markerHandle = New-Object IO.FileStream(
    $markerPath,
    [IO.FileMode]::Open,
    [IO.FileAccess]::Read,
    [IO.FileShare]::Read
)
try {
    $failedAtDeferredMarker = $false
    try {
        [TicketboxExactTreeDeleteNativeMethods]::DeleteTree(
            $root,
            $markerLeaf,
            [Action]{
                if (-not [IO.File]::Exists($markerPath)) {
                    throw 'deferred marker disappeared before the root callback'
                }
            }
        )
    }
    catch {
        $failedAtDeferredMarker = $true
    }
    if (-not $failedAtDeferredMarker -or -not [IO.File]::Exists($markerPath)) {
        throw 'the held deferred marker did not remain authoritative until last'
    }
    foreach ($path in @($hostileFiles + $hostileDirectory)) {
        if ([IO.File]::Exists($path) -or [IO.Directory]::Exists($path)) {
            throw "literal hostile child was not deleted before the deferred marker: $path"
        }
    }
}
finally {
    $markerHandle.Dispose()
}

[TicketboxExactTreeDeleteNativeMethods]::DeleteTree(
    $root,
    $markerLeaf,
    [Action]$null
)
if ([IO.Directory]::Exists($extendedRoot)) {
    throw 'exact-tree retry did not remove the root after marker release'
}
"""
        script = script.replace("@SAFETY@", _ps_literal(SAFETY_SCRIPT)).replace(
            "@ROOT@",
            _ps_literal(case_root),
        )
        harness = tmp_path / f"exact-hostile-tree-{index}.ps1"
        harness.write_text(script, encoding="utf-8-sig")
        _run_harness(engine, harness)
