"""Tests for /owner/backups page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def test_owner_backups_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    assert "数据库备份" in resp.text


def test_owner_backups_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/owner/backups")
    assert resp.status_code == 403


def test_owner_backups_skip_invalid_dump_files(local_client: TestClient) -> None:
    del local_client
    from app.services import backup_service

    # A file with the right name but garbage bytes is not a readable pg_dump
    # archive — list_backups must filter it out and is_backup_valid must reject
    # it (holds whether or not pg_restore is installed on the runner).
    bogus = backup_service._backup_dir() / "ticketbox-29991231-235959.dump"  # noqa: SLF001
    bogus.write_bytes(b"not a pg_dump archive")
    try:
        assert backup_service.is_backup_valid(bogus.name) is False
        assert bogus.name not in {entry.file_name for entry in backup_service.list_backups()}
    finally:
        bogus.unlink(missing_ok=True)


def test_owner_backups_no_uploads_path_leak(local_client: TestClient) -> None:
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    # The page must not surface the absolute uploads/data path of the host.
    assert "C:\\" not in resp.text
    assert "E:\\" not in resp.text


def test_owner_backups_post_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/owner/backups")
    assert resp.status_code == 403
