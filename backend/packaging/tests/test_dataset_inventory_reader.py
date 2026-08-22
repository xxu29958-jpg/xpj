from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]


def _installed_reader(tmp_path: Path) -> tuple[Path, Path]:
    install = tmp_path / "installer"
    install.mkdir()
    shutil.copy2(PACKAGING / "windows_dataset_inventory.ps1", install)
    (install / "windows_installation_safety.ps1").write_text("", encoding="utf-8-sig")
    (install / "windows_release_config.ps1").write_text("", encoding="utf-8-sig")
    (install / "windows_database_generation.ps1").write_text(
        """
function Get-TicketboxDatabaseGenerationExecutionDependencyPaths { param($Root); return @() }
function Assert-TicketboxDatabaseGenerationExactProperties {
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join "`n") -cne ($expected -join "`n")) { throw "$Label is open." }
}
""",
        encoding="utf-8-sig",
    )
    (install / "windows_installed_dataset_reader.ps1").write_text(
        """
function Assert-TicketboxInstalledDatasetSubject {
    param($DataRoot)
    return [pscustomobject]@{ Identity = [pscustomobject]@{
        DataRoot = $DataRoot
        BackendServiceName = 'ticketbox-backend'
    } }
}
function Get-TicketboxPathEntryKindNoFollow {
    param($Path)
    if ([IO.File]::Exists($Path)) { return 'File' }
    if ([IO.Directory]::Exists($Path)) { return 'Directory' }
    return 'Missing'
}
function Assert-TicketboxProtectedDirectoryAcl { param($Path) }
function Read-TicketboxProtectedUtf8Artifact {
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount, $MaximumBytes)
    if (-not [IO.File]::Exists($Path)) { throw 'artifact is missing.' }
    return [pscustomobject]@{ Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) }
}
""",
        encoding="utf-8-sig",
    )
    data_root = tmp_path / "data"
    (data_root / "app").mkdir(parents=True)
    return install / "windows_dataset_inventory.ps1", data_root


def _run_reader(engine: str, script: Path, data_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            script,
            "-DataRoot",
            data_root,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=30,
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_installed_inventory_reader_maps_only_missing_projection_to_empty(tmp_path: Path) -> None:
    script, data_root = _installed_reader(tmp_path)
    (data_root / "backups").mkdir()
    for engine in powershell_contract_engines():
        result = _run_reader(engine, script, data_root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["generations"] == []
    (data_root / "app" / "backup-inventory.json").write_text(
        json.dumps(
            {
                "schema": "ticketbox-complete-backup-inventory-v1",
                "generations": [],
            }
        ),
        encoding="utf-8",
    )
    for engine in powershell_contract_engines():
        result = _run_reader(engine, script, data_root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["generations"] == []


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_installed_inventory_reader_rejects_missing_backup_root(tmp_path: Path) -> None:
    script, data_root = _installed_reader(tmp_path)
    for engine in powershell_contract_engines():
        result = _run_reader(engine, script, data_root)
        assert result.returncode != 0
        assert "backup root is not a plain directory" in (result.stdout + result.stderr)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_installed_inventory_reader_rejects_missing_projection_with_backup_state(
    tmp_path: Path,
) -> None:
    script, data_root = _installed_reader(tmp_path)
    backup_root = data_root / "backups"
    backup_root.mkdir()
    (backup_root / ".ticketbox-backup-incomplete").mkdir()
    for engine in powershell_contract_engines():
        result = _run_reader(engine, script, data_root)
        assert result.returncode != 0
        assert "inventory is missing while backup state exists" in (result.stdout + result.stderr)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_installed_inventory_reader_rejects_non_array_generations(tmp_path: Path) -> None:
    script, data_root = _installed_reader(tmp_path)
    inventory = data_root / "app" / "backup-inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema": "ticketbox-complete-backup-inventory-v1",
                "generations": {"generation": "ticketbox-backup-11111111-1111-4111-8111-111111111111"},
            }
        ),
        encoding="utf-8",
    )
    for engine in powershell_contract_engines():
        result = _run_reader(engine, script, data_root)
        assert result.returncode != 0
        assert "contract drifted" in (result.stdout + result.stderr)
