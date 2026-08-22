from __future__ import annotations

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
        "TicketboxBoundaryCheck",
    ]
    for row in rows:
        assert row.available is False
        assert row.note == "非 Windows 主机"


def test_list_windows_tasks_handles_missing_schtasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise FileNotFoundError("schtasks not installed")

    monkeypatch.setattr(subprocess, "run", _raise)
    rows = wts.list_windows_tasks(force_refresh=True)
    assert all(row.available is False for row in rows)
    assert all(row.note == "未找到 schtasks.exe" for row in rows)


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

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _CompletedStub())
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


def test_list_windows_tasks_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XPJ_WINDOWS_TASK_NAMES", "MyBackend, MyTunnel")
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    rows = wts.list_windows_tasks(force_refresh=True)
    assert [row.name for row in rows] == ["MyBackend", "MyTunnel"]


def test_owner_index_renders_windows_tasks_section(local_client: TestClient) -> None:
    assert "Windows 计划任务" in local_client.get("/owner").text


def test_owner_index_no_secret_leak_with_tasks(local_client: TestClient, *, identity) -> None:
    body = local_client.get("/owner").text
    assert identity.app_token not in body
    assert identity.admin_token not in body


def test_owner_index_marks_nonzero_task_result_red(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
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


def test_database_only_backup_producers_are_physically_retired() -> None:
    project_root = Path(__file__).resolve().parents[2]
    assert not (project_root / "backend/scripts/backup_database.ps1").exists()
    maintenance = (project_root / "scripts/maintenance_ticketbox.ps1").read_text(
        encoding="utf-8-sig",
    )
    task_installer = (project_root / "scripts/install_windows_tasks.ps1").read_text(
        encoding="utf-8-sig",
    )
    assert "backup_database.ps1" not in maintenance
    assert "Backup-Database" not in maintenance
    assert "TicketboxBackup" not in task_installer


def test_cloudflare_endpoint_script_does_not_accept_token_params() -> None:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "scripts/check_cloudflare_endpoint.ps1").read_text(
        encoding="utf-8-sig",
    )
    assert "[string]$SessionToken" not in text
    assert "[string]$UploadLink" not in text
    assert "$env:TICKETBOX_SESSION_TOKEN =" not in text
    assert "$env:TICKETBOX_UPLOAD_LINK =" not in text
    preflight = (project_root / "scripts/real_device_preflight.ps1").read_text(
        encoding="utf-8-sig",
    )
    tunnel_contract = (project_root / "docs/runbook/CLOUDFLARE_TUNNEL.md").read_text(
        encoding="utf-8-sig",
    )
    assert "/api/system/runtime-compatibility" in preflight
    assert '$runtimeCompatibility.read_compatibility -ne "compatible"' in preflight
    assert '$runtimeCompatibility.write_compatibility -ne "compatible"' in preflight
    assert '"Ticketbox-Api-Version"' in preflight
    assert '"Ticketbox-Currency-Binding"' in preflight
    assert '"ADOPTION_REQUIRED"' not in preflight
    assert "system/runtime-compatibility$" in tunnel_contract
    public_boundary = (project_root / "scripts/check_public_boundary.ps1").read_text(
        encoding="utf-8-sig",
    )
    assert "public /api/system/runtime-compatibility (no token)" in public_boundary
    assert "-ExpectedStatus @(401)" in public_boundary


def test_public_boundary_script_allows_edge_catchall_for_forbidden_paths() -> None:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "scripts/check_public_boundary.ps1").read_text(
        encoding="utf-8-sig",
    )
    assert "[string[]]$ExpectedErrors" in text
    assert "@(403, 404)" in text
    assert "route_not_found', ''" in text


def test_windows_task_status_script_exits_nonzero_on_failed_task() -> None:
    project_root = Path(__file__).resolve().parents[2]
    text = (project_root / "scripts/check_windows_task_status.ps1").read_text(
        encoding="utf-8-sig",
    )
    assert "Test-TaskResultFailure" in text
    assert "exit 1" in text
