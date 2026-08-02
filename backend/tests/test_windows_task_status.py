"""T27: Windows scheduled task status read-only display."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local
from app.services import windows_task_status_service as wts


def _assert_backup_script_contract(
    completed: subprocess.CompletedProcess[str],
    *,
    capture_path: Path,
    explicit_offsite: Path,
) -> None:
    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads([line for line in completed.stdout.splitlines() if line.strip()][-1])
    capture = json.loads(capture_path.read_text(encoding="utf-8-sig"))
    arguments = capture["Arguments"]
    assert capture["PgPassword"] is None
    assert capture["PassFileExists"] is True
    assert capture["PassFileText"] == "localhost:5432:db:ticketbox:p@ss\\:word/?#%\n"
    assert capture["TimeoutMilliseconds"] == 600_000
    assert capture["Label"] == "pg_dump"
    assert not Path(capture["PassFile"]).exists()
    assert "p@ss:word/?#%" not in arguments
    assert "p%40ss%3Aword%2F%3F%23%25" not in " ".join(arguments)
    assert "--no-password" in arguments
    assert "--lock-wait-timeout=30000" in arguments
    assert arguments[arguments.index("--dbname") + 1] == (
        "postgresql://ticketbox@localhost:5432/db?require_auth=scram-sha-256"
    )
    assert result["ParentPassword"] == "parent-password"
    assert result["ParentPassFile"] == "parent-passfile"
    assert result["DefaultOffsite"] is None
    assert result["EnabledOffsite"] == str(explicit_offsite)
    assert result["MissingDirectoryFailed"] is True
    assert result["EncodedQueryPasswordFailed"] is True


def _run_backup_script_contract(engine: str, script_path: Path, tmp_path: Path) -> None:
    capture_path = tmp_path / "pg_dump_capture.json"
    target_path = tmp_path / "scheduled.dump"
    explicit_offsite = tmp_path / "explicit-offsite"
    harness = tmp_path / f"backup_contract_{Path(engine).stem}.ps1"
    harness.write_text(
        fr""". '{script_path}'
function Get-PgDumpBinary {{ return '{engine}' }}
function Invoke-TicketboxBoundedNativeProcess {{
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$TimeoutMilliseconds,
        [string]$Label
    )
    $passFile = $env:PGPASSFILE
    $passFileText = [System.IO.File]::ReadAllText($passFile, [System.Text.Encoding]::UTF8)
    $capture = [ordered]@{{
        Arguments = @($Arguments)
        PgPassword = $env:PGPASSWORD
        PassFile = $passFile
        PassFileExists = Test-Path -LiteralPath $passFile
        PassFileText = $passFileText
        TimeoutMilliseconds = $TimeoutMilliseconds
        Label = $Label
    }}
    $capture | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:XPJ_BACKUP_CAPTURE -Encoding UTF8
    $fileIndex = [Array]::IndexOf([object[]]$Arguments, '--file')
    [System.IO.File]::WriteAllBytes([string]$Arguments[$fileIndex + 1], [byte[]](1, 2, 3))
    return [pscustomobject]@{{ ExitCode = 0; StandardOutput = ''; StandardError = '' }}
}}
function Test-PostgresBackup {{ param([string]$Path) }}
$env:XPJ_BACKUP_CAPTURE = '{capture_path}'
$env:PGPASSWORD = 'parent-password'
$env:PGPASSFILE = 'parent-passfile'
Backup-PostgresDatabase `
    -DatabaseUrl 'postgresql+psycopg://ticketbox:p%40ss%3Aword%2F%3F%23%25@localhost:5432/db?require_auth=scram-sha-256' `
    -TargetPath '{target_path}'
$parentPassword = $env:PGPASSWORD
$parentPassFile = $env:PGPASSFILE
$env:OneDrive = '{tmp_path / "automatic-onedrive"}'
Remove-Item Env:\XPJ_OFFSITE_BACKUP_ENABLED -ErrorAction SilentlyContinue
Remove-Item Env:\XPJ_OFFSITE_BACKUP_DIR -ErrorAction SilentlyContinue
$defaultOffsite = Get-OffsiteBackupDir
$env:XPJ_OFFSITE_BACKUP_ENABLED = 'true'
$env:XPJ_OFFSITE_BACKUP_DIR = '{explicit_offsite}'
$enabledOffsite = Get-OffsiteBackupDir
Remove-Item Env:\XPJ_OFFSITE_BACKUP_DIR
$missingDirectoryFailed = $false
try {{ Get-OffsiteBackupDir | Out-Null }} catch {{ $missingDirectoryFailed = $true }}
$encodedQueryPasswordFailed = $false
try {{
    ConvertTo-PgDumpConnection -Url 'postgresql://ticketbox@localhost/db?require_auth=scram-sha-256&%70assword=query-secret'
}} catch {{ $encodedQueryPasswordFailed = $true }}
[ordered]@{{
    ParentPassword = $parentPassword
    ParentPassFile = $parentPassFile
    DefaultOffsite = $defaultOffsite
    EnabledOffsite = $enabledOffsite
    MissingDirectoryFailed = $missingDirectoryFailed
    EncodedQueryPasswordFailed = $encodedQueryPasswordFailed
}} | ConvertTo-Json -Compress
""",
        encoding="utf-8-sig",
    )
    completed = subprocess.run(  # noqa: S603
        [engine, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    _assert_backup_script_contract(
        completed,
        capture_path=capture_path,
        explicit_offsite=explicit_offsite,
    )


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    wts.reset_cache()
    yield
    wts.reset_cache()


def test_list_windows_tasks_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    rows = wts.list_windows_tasks(force_refresh=True)
    assert [row.name for row in rows] == [
        "TicketboxBackend",
        "TicketboxCloudflareTunnel",
        "TicketboxBackup",
        "TicketboxBoundaryCheck",
    ]
    for row in rows:
        assert row.available is False
        assert row.note == "非 Windows 主机"


def test_list_windows_tasks_handles_missing_schtasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise FileNotFoundError("schtasks not installed")

    monkeypatch.setattr(subprocess, "run", _raise)
    rows = wts.list_windows_tasks(force_refresh=True)
    assert all(r.available is False for r in rows)
    assert all(r.note == "未找到 schtasks.exe" for r in rows)


def test_list_windows_tasks_parses_schtasks_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    csv_payload = (
        '"HostName","TaskName","Status","Last Run Time","Last Result",'
        '"Next Run Time","Task To Run"\n'
        '"HOST","\\TicketboxBackend","Ready","2025/11/01 09:00:00","0",'
        '"2025/11/02 09:00:00","cmd"\n'
    )

    class _CompletedStub:
        returncode = 0
        stdout = csv_payload.encode("utf-8")

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _CompletedStub())
    rows = wts.list_windows_tasks(force_refresh=True)
    assert rows[0].available is True
    assert rows[0].status == "Ready"
    assert rows[0].last_run == "2025/11/01 09:00:00"
    assert rows[0].next_run == "2025/11/02 09:00:00"


def test_task_scheduler_information_codes_are_not_failure_notes() -> None:
    assert wts._parse_last_result("0x41301") == 0x41301
    assert wts._parse_last_result("267009") == 0x41301
    assert "正在运行" in wts._last_result_note("267009")
    assert "尚未运行" in wts._last_result_note("0x41303")
    assert wts._last_result_note("0") == ""
    assert "非零" in wts._last_result_note("1")
    assert wts._last_result_failed("1") is True
    assert wts._last_result_failed("0") is False
    assert wts._last_result_failed("0x41301") is False
    assert wts._last_result_failed("267009") is False


def test_list_windows_tasks_uses_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XPJ_WINDOWS_TASK_NAMES", "MyBackend, MyTunnel")
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    rows = wts.list_windows_tasks(force_refresh=True)
    assert [r.name for r in rows] == ["MyBackend", "MyTunnel"]


def test_owner_index_renders_windows_tasks_section(local_client: TestClient) -> None:
    body = local_client.get("/owner").text
    # On the CI/dev host (non-Windows or no tasks) the section still renders
    # because list_windows_tasks always returns degraded rows so operators
    # know the integration is wired.
    assert "Windows 计划任务" in body


def test_owner_index_no_secret_leak_with_tasks(local_client: TestClient, *, identity) -> None:
    body = local_client.get("/owner").text
    assert identity.app_token not in body
    assert identity.admin_token not in body


def test_owner_index_marks_nonzero_task_result_red(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        wts,
        "list_windows_tasks",
        lambda *_, **__: [
            wts.TaskStatusVM(
                name="TicketboxBoundaryCheck",
                available=True,
                status="Ready",
                last_run="2026/05/23 04:00:00",
                last_result="1",
                next_run="2026/05/24 04:00:00",
                last_result_failed=True,
            )
        ],
    )

    body = local_client.get("/owner").text
    assert "TicketboxBoundaryCheck" in body
    assert 'badge badge-err">1<' in body


def test_db_maintenance_scripts_resolve_configured_database_url(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    backup_text = (
        project_root / "backend" / "scripts" / "backup_database.ps1"
    ).read_text(encoding="utf-8-sig")
    maintenance_text = (
        project_root / "scripts" / "maintenance_ticketbox.ps1"
    ).read_text(encoding="utf-8-sig")
    task_text = (project_root / "scripts" / "install_windows_tasks.ps1").read_text(
        encoding="utf-8-sig"
    )

    # backup_database.ps1 is the dialect single-source: read DATABASE_URL, require
    # PostgreSQL, dump via pg_dump and validate via pg_restore --list.
    assert "DATABASE_URL" in backup_text
    assert "app.services.postgres_backup_validation_service" in backup_text
    assert "ConvertTo-PgDumpConnection" in backup_text
    assert "XPJ_OFFSITE_BACKUP_ENABLED" in backup_text
    assert "--dbname', $ProtectedDatabaseUrl" in backup_text
    assert "Invoke-TicketboxBoundedNativeProcess" in backup_text
    assert "--no-password" in backup_text
    assert "--lock-wait-timeout=30000" in backup_text
    assert "--dbname $libpqUrl" not in backup_text
    assert "Join-Path $env:OneDrive" not in backup_text
    assert "SpecialFolder]::ProgramFiles" in backup_text
    assert 'GetEnvironmentVariable("ProgramFiles", "Machine")' not in backup_text
    assert r"C:\Program Files\PostgreSQL" not in backup_text
    assert backup_text.index("Backup-PostgresDatabase -DatabaseUrl") < backup_text.index(
        "$offsiteDir = Get-OffsiteBackupDir"
    )

    # The scheduled maintenance task delegates its backup to backup_database.ps1
    # rather than resolving the database itself.
    assert "backup_database.ps1" in maintenance_text
    assert "BackupTaskExecutionTimeLimitMinutes" in task_text
    assert "-ExecutionTimeLimit (New-TimeSpan -Minutes $BackupTaskExecutionTimeLimitMinutes)" in task_text

    # PostgreSQL-only (ADR-0041): neither script keeps the retired SQLite backup/
    # validation path or a hardcoded SQLite file path.
    for text in (backup_text, maintenance_text):
        assert '$DbPath = Join-Path $BackendRoot "data\\ticketbox.db"' not in text
        assert "Resolve-DbPath" not in text
        assert "sqlite_backup_validation_service" not in text
        assert "Backup-SqliteDatabase" not in text

    if sys.platform == "win32":
        engines = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
        for engine in engines:
            _run_backup_script_contract(
                engine,
                project_root / "backend/scripts/backup_database.ps1",
                tmp_path,
            )


def test_windows_postgres_discovery_uses_os_program_files_contract() -> None:
    project_root = Path(__file__).resolve().parents[2]
    script_paths = (
        project_root / "backend" / "scripts" / "backup_database.ps1",
        project_root / "backend" / "packaging" / "install_ticketbox.ps1",
    )

    for script_path in script_paths:
        script = script_path.read_text(encoding="utf-8-sig")
        assert "SpecialFolder]::ProgramFiles" in script
        assert 'GetEnvironmentVariable("ProgramFiles", "Machine")' not in script
        assert r"C:\Program Files\PostgreSQL" not in script


def test_cloudflare_endpoint_script_does_not_accept_token_params() -> None:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "scripts" / "check_cloudflare_endpoint.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "[string]$SessionToken" not in text
    assert "[string]$UploadLink" not in text
    assert "$env:TICKETBOX_SESSION_TOKEN =" not in text
    assert "$env:TICKETBOX_UPLOAD_LINK =" not in text
    preflight = (project_root / "scripts" / "real_device_preflight.ps1").read_text(
        encoding="utf-8-sig"
    )
    tunnel_contract = (project_root / "docs" / "runbook" / "CLOUDFLARE_TUNNEL.md").read_text(
        encoding="utf-8-sig"
    )
    assert "/api/system/currency-capability" in preflight
    assert '$currencyCapability.health -eq "empty"' in preflight
    assert '$currencyCapability.health -eq "active_match"' in preflight
    assert '$currencyCapability.initialization_offer -eq "CNY"' in preflight
    assert '$currencyCapability.home_currency_code -eq "CNY"' in preflight
    assert "$bindingRevision -eq 0" in preflight
    assert "$bindingRevision -eq 1" in preflight
    assert '"ADOPTION_REQUIRED"' not in preflight
    assert "system/currency-capability$" in tunnel_contract


def test_public_boundary_script_allows_edge_catchall_for_forbidden_paths() -> None:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "scripts" / "check_public_boundary.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "[string[]]$ExpectedErrors" in text
    assert "@(403, 404)" in text
    assert "route_not_found', ''" in text


def test_windows_task_status_script_exits_nonzero_on_failed_task() -> None:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "scripts" / "check_windows_task_status.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "Test-TaskResultFailure" in text
    assert "exit 1" in text
