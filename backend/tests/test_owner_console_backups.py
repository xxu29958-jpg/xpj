"""Read-only Owner Console view of complete dataset backup generations."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def _stub_latest_backup(monkeypatch: pytest.MonkeyPatch, *, hours_ago: int | None):
    from app.services import backup_service
    from app.services.time_service import now_utc

    if hours_ago is None:
        monkeypatch.setattr(backup_service, "latest_backup", lambda: None)
        return None
    entry = backup_service.BackupEntry(
        file_name="ticketbox-backup-8c78c277-9e2e-48cd-86a2-7a9087d650a2",
        backup_id="8c78c277-9e2e-48cd-86a2-7a9087d650a2",
        dataset_id="40f0c00b-ef2b-4141-b17c-aebd2da988e2",
        restore_epoch=2,
        size_bytes=4096,
        created_at=now_utc() - timedelta(hours=hours_ago),
        kind="scheduled",
    )
    monkeypatch.setattr(backup_service, "latest_backup", lambda: entry)
    return entry


def test_owner_backups_page_is_read_only_complete_generation_view(
    local_client: TestClient,
) -> None:
    response = local_client.get("/owner/backups")
    assert response.status_code == 200
    assert "完整备份" in response.text
    assert "数据库、原始票据附件、数据集身份和校验清单" in response.text
    assert 'method="post" action="/owner/backups"' not in response.text
    assert local_client.post("/owner/backups").status_code == 405


def test_owner_backups_remote_returns_403(client: TestClient) -> None:
    assert client.get("/owner/backups").status_code == 403


def test_incomplete_generation_is_not_listed(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import backup_service

    bogus = tmp_path / "ticketbox-backup-a0c5f82d-c95e-452a-8f7a-dba0f0850758"
    bogus.mkdir()
    (bogus / "database.dump").write_bytes(b"database-only")
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)

    assert backup_service.list_backups() == []
    assert backup_service.is_backup_valid(bogus.name) is False
    assert bogus.name not in local_client.get("/owner/backups").text


def test_backup_health_uses_only_complete_generation_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import backup_service

    entry = _stub_latest_backup(monkeypatch, hours_ago=72)
    health = backup_service.backup_health()
    assert health.latest is entry
    assert health.age_hours == 72
    assert health.stale is True


def test_owner_page_never_leaks_absolute_data_path(local_client: TestClient) -> None:
    response = local_client.get("/owner/backups")
    assert response.status_code == 200
    assert "C:\\" not in response.text
    assert "E:\\" not in response.text
