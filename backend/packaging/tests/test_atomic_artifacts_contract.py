from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
ENTRYPOINT = PACKAGING / "windows_atomic_artifacts.ps1"
NATIVE = PACKAGING / "atomic_artifacts" / "native.ps1"
FILE = PACKAGING / "atomic_artifacts" / "file.ps1"
DIRECTORY = PACKAGING / "atomic_artifacts" / "directory.ps1"
TARGET_RECOVERY = PACKAGING / "windows_database_generation_recovery_evidence.ps1"


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _function(source: str, name: str) -> str:
    start = source.index(f"function {name} {{")
    next_function = source.find("\nfunction ", start + 1)
    return source[start:] if next_function < 0 else source[start:next_function]


def test_atomic_artifacts_are_focused_bom_safe_and_not_c07() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8-sig")
    native = NATIVE.read_text(encoding="utf-8-sig")
    file_source = FILE.read_text(encoding="utf-8-sig")
    directory = DIRECTORY.read_text(encoding="utf-8-sig")

    for path, source in (
        (ENTRYPOINT, entrypoint),
        (NATIVE, native),
        (FILE, file_source),
        (DIRECTORY, directory),
    ):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert source.startswith("#Requires -Version 5.1")
        assert len(source.splitlines()) <= 300
        assert "c07" not in source.lower()

    assert '"native.ps1"' in entrypoint
    assert '"file.ps1"' in entrypoint
    assert '"directory.ps1"' in entrypoint
    assert "CREATE_NEW" in native
    assert "FILE_FLAG_OPEN_REPARSE_POINT" in native
    assert "GetFinalPathNameByHandle" in native
    assert "MOVEFILE_WRITE_THROUGH" in native
    assert "Sync-TicketboxDurableArtifactFile" in file_source
    assert "Copy-TicketboxVerifiedArtifact" in file_source
    assert "Publish-TicketboxVerifiedArtifactDirectory" in directory


def test_atomic_durability_identity_and_verify_before_publish_are_pinned() -> None:
    file_source = FILE.read_text(encoding="utf-8-sig")
    directory_source = DIRECTORY.read_text(encoding="utf-8-sig")
    target_recovery = TARGET_RECOVERY.read_text(encoding="utf-8-sig")

    durable_sync = _function(file_source, "Sync-TicketboxDurableArtifactFile")
    assert durable_sync.index("::GetFinalPath(") < durable_sync.index(
        "Test-TicketboxPathEquals $finalPath $Path"
    )
    assert durable_sync.index("Test-TicketboxPathEquals $finalPath $Path") < (
        durable_sync.index("::AssertHandleIsNotReparsePoint(")
    )
    assert durable_sync.index("::AssertHandleIsNotReparsePoint(") < durable_sync.index(
        "$stream.Flush($true)"
    )

    verified_copy = _function(file_source, "Copy-TicketboxVerifiedArtifact")
    assert verified_copy.count("::GetFinalPath(") == 4
    assert verified_copy.count("Test-TicketboxPathEquals") == 4
    first_flush = verified_copy.index("$destination.Flush($true)")
    length_readback = verified_copy.index("$destination.Length -ne $ExpectedLength")
    digest_seek = verified_copy.index("$destination.Position = 0")
    digest_readback = verified_copy.index("$destinationSha.ComputeHash($destination)")
    digest_compare = verified_copy.index("$destinationDigest -cne $sourceDigest")
    second_flush = verified_copy.index("$destination.Flush($true)", first_flush + 1)
    acl_set = verified_copy.index("Set-TicketboxExactFileAcl")
    acl_readback = verified_copy.index("Assert-TicketboxExactFileAcl")
    protected_identity = verified_copy.index("$finalProtectedDestination")
    assert (
        first_flush
        < length_readback
        < digest_seek
        < digest_readback
        < digest_compare
        < second_flush
        < acl_set
        < acl_readback
        < protected_identity
    )

    directory_publish = _function(
        directory_source,
        "Publish-TicketboxVerifiedArtifactDirectory",
    )
    assert directory_publish.count("::GetFinalPath(") == 2
    assert directory_publish.count("Test-TicketboxPathEquals") == 4
    assert directory_publish.index("$finalGenerationRoot") < directory_publish.index(
        "::MoveDirectoryWriteThrough("
    )
    assert directory_publish.index("::MoveDirectoryWriteThrough(") < (
        directory_publish.index("$finalReady")
    )

    archive = _function(
        target_recovery,
        "Get-TicketboxDatabaseGenerationRecoveryArchive",
    )
    assert archive.index("Sync-TicketboxFileDurable $paths.PartialPath") < archive.index(
        "Copy-TicketboxVerifiedArtifact"
    )
    copy_index = archive.index("Copy-TicketboxVerifiedArtifact")
    assert copy_index < archive.index(
        "Remove-TicketboxDatabaseGenerationRecoveryFile", copy_index
    )


def test_generation_recovery_consumes_atomic_artifacts_without_a_parallel_writer() -> None:
    source = TARGET_RECOVERY.read_text(encoding="utf-8-sig")

    assert "Copy-TicketboxVerifiedArtifact" in source
    assert "Move-TicketboxFileDurable $paths.PartialPath $paths.Path" not in source
    assert "windows_c07_recovery_generation.ps1" not in source


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_verified_copy_is_create_new_hash_bound_and_read_back(
    engine: str,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    mismatch_destination = tmp_path / "mismatch.bin"
    source_bytes = b"ticketbox-atomic-artifact\x00\x01\x02"
    source_path.write_bytes(source_bytes)
    expected_sha = hashlib.sha256(source_bytes).hexdigest()
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(ENTRYPOINT)}'

function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (-not [IO.File]::Exists($Path) -and -not [IO.Directory]::Exists($Path)) {{
        return 'Missing'
    }}
    $attributes = [IO.File]::GetAttributes($Path)
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {{
        return 'ReparsePoint'
    }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'File'
}}
$script:setAcl = 0
$script:assertAcl = 0
function Set-TicketboxExactFileAcl {{ param($Path, $Accounts, $OwnerAccount) $script:setAcl++ }}
function Assert-TicketboxExactFileAcl {{ param($Path, $Accounts, $OwnerAccount) $script:assertAcl++ }}

$copy = Copy-TicketboxVerifiedArtifact `
    -SourcePath '{_literal(source_path)}' `
    -DestinationPath '{_literal(destination)}' `
    -ExpectedSourceSha256 '{expected_sha}' `
    -ExpectedLength ([int64]{len(source_bytes)}) `
    -FullControlAccounts @('SYSTEM') `
    -OwnerAccount 'SYSTEM'
if ($copy.Sha256 -cne '{expected_sha}' -or
    $copy.SizeBytes -ne {len(source_bytes)} -or
    $script:setAcl -ne 1 -or $script:assertAcl -ne 1 -or
    -not [IO.File]::Exists('{_literal(destination)}')) {{
    throw 'verified copy did not cross exactly one verified ACL boundary'
}}

$existingRejected = $false
try {{
    Copy-TicketboxVerifiedArtifact `
        -SourcePath '{_literal(source_path)}' `
        -DestinationPath '{_literal(destination)}' `
        -ExpectedSourceSha256 '{expected_sha}' `
        -ExpectedLength ([int64]{len(source_bytes)}) `
        -FullControlAccounts @('SYSTEM') `
        -OwnerAccount 'SYSTEM' | Out-Null
}}
catch {{ $existingRejected = $true }}
if (-not $existingRejected -or
    [Convert]::ToBase64String([IO.File]::ReadAllBytes('{_literal(destination)}')) -cne
        [Convert]::ToBase64String([IO.File]::ReadAllBytes('{_literal(source_path)}'))) {{
    throw 'create-new destination contract was not fail-closed'
}}

$mismatchRejected = $false
try {{
    Copy-TicketboxVerifiedArtifact `
        -SourcePath '{_literal(source_path)}' `
        -DestinationPath '{_literal(mismatch_destination)}' `
        -ExpectedSourceSha256 '{'0' * 64}' `
        -ExpectedLength ([int64]{len(source_bytes)}) `
        -FullControlAccounts @('SYSTEM') `
        -OwnerAccount 'SYSTEM' | Out-Null
}}
catch {{ $mismatchRejected = $true }}
if (-not $mismatchRejected -or [IO.File]::Exists('{_literal(mismatch_destination)}')) {{
    throw 'source hash mismatch created a destination artifact'
}}
"""
    result = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_directory_publication_is_same_volume_no_replace_and_verified(
    engine: str,
    tmp_path: Path,
) -> None:
    generation_root = tmp_path / "generations"
    generation_root.mkdir()
    partial = generation_root / "candidate.partial"
    ready = generation_root / "candidate.ready"
    partial.mkdir()
    (partial / "payload.txt").write_text("candidate", encoding="utf-8")
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(ENTRYPOINT)}'

function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (-not [IO.File]::Exists($Path) -and -not [IO.Directory]::Exists($Path)) {{
        return 'Missing'
    }}
    $attributes = [IO.File]::GetAttributes($Path)
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {{
        return 'ReparsePoint'
    }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'File'
}}
function Get-TicketboxVolumeIdentityForPath {{ param($Path) 'volume-1' }}
function Assert-TicketboxProtectedDirectoryAcl {{ param($Path, $FullControlAccounts, $OwnerAccount) }}

$published = Publish-TicketboxVerifiedArtifactDirectory `
    -GenerationRoot '{_literal(generation_root)}' `
    -PartialRoot '{_literal(partial)}' `
    -ReadyRoot '{_literal(ready)}' `
    -FullControlAccounts @('SYSTEM') `
    -OwnerAccount 'SYSTEM'
if ($published -cne '{_literal(ready)}' -or
    [IO.Directory]::Exists('{_literal(partial)}') -or
    -not [IO.File]::Exists((Join-Path '{_literal(ready)}' 'payload.txt'))) {{
    throw 'directory publication did not reach exactly one terminal name'
}}

[IO.Directory]::CreateDirectory('{_literal(partial)}') | Out-Null
[IO.File]::WriteAllText(
    (Join-Path '{_literal(partial)}' 'new.txt'),
    'new',
    [Text.UTF8Encoding]::new($false)
)
$replaceRejected = $false
try {{
    Publish-TicketboxVerifiedArtifactDirectory `
        -GenerationRoot '{_literal(generation_root)}' `
        -PartialRoot '{_literal(partial)}' `
        -ReadyRoot '{_literal(ready)}' `
        -FullControlAccounts @('SYSTEM') `
        -OwnerAccount 'SYSTEM' | Out-Null
}}
catch {{ $replaceRejected = $true }}
if (-not $replaceRejected -or
    -not [IO.Directory]::Exists('{_literal(partial)}') -or
    -not [IO.File]::Exists((Join-Path '{_literal(ready)}' 'payload.txt'))) {{
    throw 'pre-existing published directory was replaced'
}}
"""
    result = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
