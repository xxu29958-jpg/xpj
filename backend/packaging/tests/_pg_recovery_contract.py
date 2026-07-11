"""Behavior harness for the protected PostgreSQL uninstall recovery point."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

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
    engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
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
$saved = Save-TicketboxPgRecoveryToolset `
    -SourcePgHome '{_literal(source)}' `
    -BuildManifestPath '{_literal(manifest)}' `
    -ExpectedMajor 17
if ($saved.Snapshot.fingerprint -cne '{fingerprint}') {{ throw 'saved fingerprint mismatch' }}
$verified = Assert-TicketboxPgRecoveryToolset -ExpectedMajor 17
if ($verified.Snapshot.files.Count -ne {count}) {{ throw 'saved file count mismatch' }}
[System.IO.File]::AppendAllText((Join-Path $verified.Home 'bin\\postgres.exe'), 'tampered')
$tamperRejected = $false
try {{ Assert-TicketboxPgRecoveryToolset -ExpectedMajor 17 | Out-Null }}
catch {{ $tamperRejected = $true }}
if (-not $tamperRejected) {{ throw 'tampered recovery payload was accepted' }}
Remove-TicketboxKnownPgRecoveryDirectory (Get-TicketboxPgRecoveryRoot)
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
