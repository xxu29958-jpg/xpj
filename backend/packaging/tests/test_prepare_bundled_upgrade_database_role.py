from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

ROOT = Path(__file__).resolve().parents[3]
PACKAGING = ROOT / "backend" / "packaging"
PREPARE_PATH = PACKAGING / "prepare_bundled_upgrade.ps1"
DATABASE_SAFETY_PATH = PACKAGING / "windows_database_safety.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _powershell_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    next_function = source.find("\nfunction ", start + len("function "))
    assert next_function > start
    return source[start:next_function]


def test_prepare_upgrade_routes_both_backup_modes_through_registered_role_gate() -> None:
    prepare = _read(PREPARE_PATH)
    helper_name = "Get-TicketboxPreparedApplicationDatabaseConnection"

    assert '$script:TicketboxPreparedRuntimeDatabaseRole = "ticketbox_runtime"' in prepare
    assert prepare.count(helper_name) == 3
    assert prepare.count("Get-TicketboxLocalDatabaseConnection") == 1

    preserved = prepare[
        prepare.index('if ($mode -eq "preserved_data_reinstall")') :
        prepare.index('elseif ($mode -ne "fresh_install")')
    ]
    assert helper_name in preserved
    assert "-ExpectedRole $DbRole" not in preserved

    backup = prepare[
        prepare.index("if ($backupRequired)", prepare.index("$installAclMutationStarted")) :
        prepare.index("Set-TicketboxLifecycleReceiptPrepared", prepare.index("$installAclMutationStarted"))
    ]
    connection_gate = backup.index(f"$connection = {helper_name}")
    connected_instance_gate = backup.index("Assert-TicketboxConnectedPostgresDataRoot")
    pg_dump = backup.index("Invoke-TicketboxPgDumpCustom")
    assert connection_gate < connected_instance_gate < pg_dump
    assert "-DatabaseUrl $connection.DatabaseUrl" in backup[connected_instance_gate:pg_dump]
    assert "-Password $connection.Password" in backup[connected_instance_gate:pg_dump]
    assert "-DatabaseUrl $connection.DatabaseUrl" in backup[pg_dump:]
    assert "-Password $connection.Password" in backup[pg_dump:]


@pytest.mark.parametrize("powershell", powershell_contract_engines())
def test_prepare_upgrade_accepts_only_registered_legacy_or_runtime_role(
    powershell: str,
    tmp_path: Path,
) -> None:
    prepare = _read(PREPARE_PATH)
    helper = _extract_function(
        prepare,
        "Get-TicketboxPreparedApplicationDatabaseConnection",
    )
    harness = tmp_path / "prepare-database-role-contract.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_powershell_literal(DATABASE_SAFETY_PATH)}'
$PgPort = 5440
$DbName = 'ticketbox'
$DbRole = 'ticketbox'
$script:TicketboxPreparedRuntimeDatabaseRole = 'ticketbox_runtime'
{helper}

$legacy = Get-TicketboxPreparedApplicationDatabaseConnection `
    -DatabaseUrl 'postgresql+psycopg://ticketbox:legacy-secret@127.0.0.1:5440/ticketbox'
$runtime = Get-TicketboxPreparedApplicationDatabaseConnection `
    -DatabaseUrl 'postgresql+psycopg://ticketbox_runtime:runtime-secret@127.0.0.1:5440/ticketbox'

$rejections = [ordered]@{{}}
$candidates = [ordered]@{{
    postgres = 'postgresql://postgres:secret@127.0.0.1:5440/ticketbox'
    foreign_database = 'postgresql://ticketbox_runtime:secret@127.0.0.1:5440/postgres'
    foreign_port = 'postgresql://ticketbox_runtime:secret@127.0.0.1:5441/ticketbox'
    foreign_host = 'postgresql://ticketbox_runtime:secret@192.0.2.10:5440/ticketbox'
    empty_password = 'postgresql://ticketbox_runtime:@127.0.0.1:5440/ticketbox'
}}
foreach ($candidate in $candidates.GetEnumerator()) {{
    $rejected = $false
    try {{
        Get-TicketboxPreparedApplicationDatabaseConnection `
            -DatabaseUrl ([string]$candidate.Value) | Out-Null
    }}
    catch {{
        $rejected = $true
    }}
    $rejections[[string]$candidate.Key] = $rejected
}}

[ordered]@{{
    legacy = [ordered]@{{
        role = [string]$legacy.Role
        database_url = [string]$legacy.DatabaseUrl
        persisted_url = [string]$legacy.PersistedDatabaseUrl
        password = [string]$legacy.Password
    }}
    runtime = [ordered]@{{
        role = [string]$runtime.Role
        database_url = [string]$runtime.DatabaseUrl
        persisted_url = [string]$runtime.PersistedDatabaseUrl
        password = [string]$runtime.Password
    }}
    rejections = $rejections
}} | ConvertTo-Json -Depth 5 -Compress
""",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [
            powershell,
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
        encoding="utf-8-sig",
        errors="replace",
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())

    assert payload["legacy"]["role"] == "ticketbox"
    assert payload["runtime"]["role"] == "ticketbox_runtime"
    assert payload["legacy"]["password"] == "legacy-secret"
    assert payload["runtime"]["password"] == "runtime-secret"
    for authority in ("legacy", "runtime"):
        assert "secret" not in payload[authority]["database_url"]
        assert "require_auth=scram-sha-256" in payload[authority]["database_url"]
        assert "require_auth=scram-sha-256" in payload[authority]["persisted_url"]
        assert payload[authority]["database_url"].endswith(
            "/ticketbox?require_auth=scram-sha-256"
        )
    assert payload["rejections"] == {
        "postgres": True,
        "foreign_database": True,
        "foreign_port": True,
        "foreign_host": True,
        "empty_password": True,
    }
