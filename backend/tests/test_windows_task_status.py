"""T27: Windows scheduled task status read-only display."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
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
    assert len(rows) == 3  # default trio
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


def test_owner_index_no_secret_leak_with_tasks(local_client: TestClient) -> None:
    import conftest as cf

    body = local_client.get("/owner").text
    assert cf.CURRENT_APP_TOKEN not in body
    assert cf.CURRENT_ADMIN_TOKEN not in body
