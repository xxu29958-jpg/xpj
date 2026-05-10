"""Tests for /owner/backups page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import conftest as cf  # noqa: F401
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


def test_owner_backups_create_makes_file(local_client: TestClient, tmp_path) -> None:
    from app.services import backup_service

    initial = len(backup_service.list_backups())
    resp = local_client.post("/owner/backups")
    assert resp.status_code == 200
    assert "备份已创建" in resp.text
    assert len(backup_service.list_backups()) == initial + 1


def test_owner_backups_no_uploads_path_leak(local_client: TestClient) -> None:
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    # The page must not surface the absolute uploads/data path of the host.
    assert "C:\\" not in resp.text
    assert "E:\\" not in resp.text


def test_owner_backups_post_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/owner/backups")
    assert resp.status_code == 403
