"""Behavior harness for the protected PostgreSQL uninstall recovery point."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _payload_snapshot(root: Path) -> tuple[str, int]:
    records: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        records.append((relative, len(payload), hashlib.sha256(payload).hexdigest()))
    material = "".join(f"{path}\0{size}\0{digest}\n" for path, size, digest in records)
    return hashlib.sha256(material.encode()).hexdigest(), len(records)


def assert_pg_recovery_toolset_behavior(tmp_path: Path) -> None:
    source = tmp_path / "source-pg"
    (source / "bin").mkdir(parents=True)
    for name in (
        "postgres.exe",
        "pg_ctl.exe",
        "pg_isready.exe",
        "psql.exe",
        "pg_dump.exe",
        "pg_restore.exe",
    ):
        (source / "bin" / name).write_bytes(f"fixture:{name}".encode())
    fingerprint, count = _payload_snapshot(source)
    manifest = tmp_path / "BUILD_PROVENANCE.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "artifact_type": "ticketbox-windows-installer-inputs",
                "postgresql": {
                    "major": 17,
                    "payload_algorithm": "SHA-256",
                    "payload_fingerprint": fingerprint,
                    "payload_file_count": count,
                },
            }
        ),
        encoding="utf-8",
    )
    engines = powershell_contract_engines()
    for index, engine in enumerate(engines):
        lifecycle = tmp_path / f"lifecycle-{index}"
        lifecycle.mkdir()
        harness = tmp_path / f"pg-recovery-{index}.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / 'windows_installation_safety.ps1')}'
. '{_literal(BACKEND / 'scripts' / 'windows_build_provenance.ps1')}'
function Get-TicketboxLifecycleLockPath {{ return '{_literal(lifecycle / 'installer-lifecycle.lock')}' }}
. '{_literal(PACKAGING / 'windows_pg_recovery_tools.ps1')}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxPgRecoveryFullControlAccounts = @($currentAccount)
$script:TicketboxPgRecoveryOwnerAccount = $currentAccount
$abandonedStaging = Join-Path `
    '{_literal(lifecycle)}' `
    '.postgresql-recovery-staging-4242-0123456789abcdef0123456789abcdef'
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path $abandonedStaging `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
New-Item -ItemType Directory -Path (Join-Path $abandonedStaging 'pg') | Out-Null
[System.IO.File]::WriteAllText((Join-Path (Join-Path $abandonedStaging 'pg') 'partial.bin'), 'partial')
$caseVariantStaging = Join-Path `
    '{_literal(lifecycle)}' `
    '.PostgreSQL-recovery-staging-4343-fedcba9876543210fedcba9876543210'
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path $caseVariantStaging `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
$caseVariantRejected = $false
try {{
    Save-TicketboxPgRecoveryToolset `
        -SourcePgHome '{_literal(source)}' `
        -BuildManifestPath '{_literal(manifest)}' `
        -ExpectedMajor 17 | Out-Null
}}
catch {{ $caseVariantRejected = $true }}
if (-not $caseVariantRejected -or -not (Test-Path -LiteralPath $caseVariantStaging)) {{
    throw 'case-variant PG staging namespace was ignored or deleted instead of rejected'
}}
Remove-TicketboxKnownPgRecoveryDirectory $caseVariantStaging
$saved = Save-TicketboxPgRecoveryToolset `
    -SourcePgHome '{_literal(source)}' `
    -BuildManifestPath '{_literal(manifest)}' `
    -ExpectedMajor 17
if (Test-Path -LiteralPath $abandonedStaging) {{
    throw 'abandoned PG recovery staging was not reaped before save'
}}
if ($saved.Snapshot.fingerprint -cne '{fingerprint}') {{ throw 'saved fingerprint mismatch' }}
$verified = Assert-TicketboxPgRecoveryToolset -ExpectedMajor 17
if ($verified.Snapshot.files.Count -ne {count}) {{ throw 'saved file count mismatch' }}
Set-TicketboxPgRecoveryAcl -ReadExecuteAccounts @('BUILTIN\\Users')
$serviceReadable = Assert-TicketboxPgRecoveryToolset `
    -ExpectedMajor 17 `
    -ReadExecuteAccounts @('BUILTIN\\Users')
if ($serviceReadable.Snapshot.fingerprint -cne '{fingerprint}') {{
    throw 'recovery service ReadExecute SID could not validate its protected toolset'
}}
Set-TicketboxPgRecoveryAcl
[System.IO.File]::AppendAllText((Join-Path $verified.Home 'bin\\postgres.exe'), 'tampered')
$tamperRejected = $false
try {{ Assert-TicketboxPgRecoveryToolset -ExpectedMajor 17 | Out-Null }}
catch {{ $tamperRejected = $true }}
if (-not $tamperRejected) {{ throw 'tampered recovery payload was accepted' }}
Remove-TicketboxKnownPgRecoveryDirectory (Get-TicketboxPgRecoveryRoot)
$saved = Save-TicketboxPgRecoveryToolset `
    -SourcePgHome '{_literal(source)}' `
    -BuildManifestPath '{_literal(manifest)}' `
    -ExpectedMajor 17
$missingDeleteAuthorityRejected = $false
try {{ Remove-TicketboxPgRecoveryToolset -ExpectedMajor 17 }}
catch {{ $missingDeleteAuthorityRejected = $true }}
if (-not $missingDeleteAuthorityRejected) {{
    throw 'PG recovery deletion accepted no completed-commit or delete-data authority'
}}
$root = Get-TicketboxPgRecoveryRoot
$conflictingDeleteAuthorityRejected = $false
try {{
    Remove-TicketboxPgRecoveryToolset `
        -ExpectedMajor 17 `
        -DeleteDataIntentValidated `
        -InstallCommitValidated
}}
catch {{ $conflictingDeleteAuthorityRejected = $true }}
if (-not $conflictingDeleteAuthorityRejected) {{
    throw 'PG recovery deletion accepted conflicting authorities'
}}
Remove-TicketboxPgRecoveryToolset `
    -ExpectedMajor 17 `
    -InstallCommitValidated
if (Test-Path -LiteralPath $root) {{ throw 'completed install commit did not retire PG recovery tools' }}
$danglingTarget = Join-Path '{_literal(lifecycle)}' 'dangling-pg-recovery-target'
New-Item -ItemType Directory -Path $danglingTarget | Out-Null
New-Item -ItemType Junction -Path $root -Target $danglingTarget | Out-Null
[System.IO.Directory]::Delete($danglingTarget)
$danglingRootRejected = $false
try {{
    Remove-TicketboxPgRecoveryToolset `
        -ExpectedMajor 17 `
        -InstallCommitValidated
}}
catch {{ $danglingRootRejected = $true }}
if (-not $danglingRootRejected -or (Get-TicketboxPathEntryKindNoFollow $root) -cne 'Reparse') {{
    throw 'dangling PG recovery root was treated as absent or modified'
}}
[System.IO.Directory]::Delete($root)
if ((Get-TicketboxPathEntryKindNoFollow $root) -cne 'Missing') {{
    throw 'dangling PG recovery junction cleanup failed in the test harness'
}}
$saved = Save-TicketboxPgRecoveryToolset `
    -SourcePgHome '{_literal(source)}' `
    -BuildManifestPath '{_literal(manifest)}' `
    -ExpectedMajor 17
$completionPath = Join-Path $root $script:TicketboxPgRecoveryCompletionName
$deletionIntentPath = Join-Path $root $script:TicketboxPgRecoveryDeletionIntentName
$completion = Read-TicketboxPgRecoveryCompletion `
    -Path $completionPath `
    -ExpectedMajor 17
$deletionIntent = [ordered]@{{
    schema = 'ticketbox-pg-recovery-delete-v1'
    pg_major = 17
    payload_fingerprint = [string]$saved.Snapshot.fingerprint
    manifest_sha256 = [string]$completion.manifest_sha256
    completion_sha256 = Get-TicketboxFileSha256 $completionPath
}}
Write-TicketboxProtectedUtf8FileDurable `
    -Path $deletionIntentPath `
    -Text (($deletionIntent | ConvertTo-Json -Depth 4) + [Environment]::NewLine) `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$deletionLease = [System.IO.File]::Open(
    $deletionIntentPath,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::Read
)
$interruptedDeleteRejected = $false
try {{
    try {{
        Remove-TicketboxPgRecoveryToolset `
            -ExpectedMajor 17 `
            -DeleteDataIntentValidated
    }}
    catch {{ $interruptedDeleteRejected = $true }}
}}
finally {{ $deletionLease.Dispose() }}
if (-not $interruptedDeleteRejected) {{
    throw 'PG recovery deletion did not preserve the final intent leaf on interruption'
}}
$remainingNames = @(Get-ChildItem -LiteralPath $root -Force | ForEach-Object {{ $_.Name }})
if ($remainingNames.Count -ne 1 -or $remainingNames[0] -cne $script:TicketboxPgRecoveryDeletionIntentName) {{
    throw "PG recovery interrupted deletion left an unauthorised residual tree: $($remainingNames -join ',')"
}}
Remove-TicketboxPgRecoveryToolset `
    -ExpectedMajor 0 `
    -DeleteDataIntentValidated
if (Test-Path -LiteralPath $root) {{ throw 'PG recovery deletion retry did not converge' }}
$saved = Save-TicketboxPgRecoveryToolset `
    -SourcePgHome '{_literal(source)}' `
    -BuildManifestPath '{_literal(manifest)}' `
    -ExpectedMajor 17
Remove-Item -LiteralPath (Join-Path $root $script:TicketboxPgRecoveryCompletionName) -Force
$markerlessPartialRejected = $false
try {{
    Remove-TicketboxPgRecoveryToolset `
        -ExpectedMajor 17 `
        -DeleteDataIntentValidated
}}
catch {{ $markerlessPartialRejected = $true }}
if (-not $markerlessPartialRejected) {{
    throw 'markerless non-empty PG recovery tree was accepted as an interrupted deletion'
}}
Remove-TicketboxKnownPgRecoveryDirectory $root
New-Item -ItemType Directory -Path $root | Out-Null
Set-TicketboxExactDirectoryAcl `
    -Path $root `
    -Accounts @($currentAccount) `
    -OwnerAccount $currentAccount
Remove-TicketboxPgRecoveryToolset `
    -ExpectedMajor 0 `
    -DeleteDataIntentValidated
if (Test-Path -LiteralPath $root) {{ throw 'empty PG recovery root retry did not converge' }}
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
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
