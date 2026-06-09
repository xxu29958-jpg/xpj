"""Tests for /owner/backups page."""

from __future__ import annotations

import sqlite3

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


def test_owner_backups_skip_invalid_partial_files(local_client: TestClient, tmp_path) -> None:
    del local_client
    from app.services import backup_service

    partial = backup_service._backup_dir() / "ticketbox-29991231-235959.db"  # noqa: SLF001
    partial.write_bytes(b"not a sqlite database")
    try:
        assert backup_service.is_backup_valid(partial.name) is False
        assert partial.name not in {entry.file_name for entry in backup_service.list_backups()}
    finally:
        partial.unlink(missing_ok=True)


def test_owner_backups_skip_foreign_key_damaged_files(local_client: TestClient) -> None:
    del local_client
    from app.services import backup_service

    damaged = backup_service._backup_dir() / "ticketbox-29991231-235958.db"  # noqa: SLF001
    conn = sqlite3.connect(damaged)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 999)")
        conn.commit()
    finally:
        conn.close()
    try:
        assert backup_service.is_backup_valid(damaged.name) is False
        assert damaged.name not in {entry.file_name for entry in backup_service.list_backups()}
    finally:
        damaged.unlink(missing_ok=True)


def test_owner_backups_skip_sqlite_files_without_ticketbox_schema(local_client: TestClient) -> None:
    del local_client
    from app.services import backup_service

    wrong_schema = backup_service._backup_dir() / "ticketbox-29991231-235957.db"  # noqa: SLF001
    conn = sqlite3.connect(wrong_schema)
    try:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    try:
        assert backup_service.is_backup_valid(wrong_schema.name) is False
        assert wrong_schema.name not in {entry.file_name for entry in backup_service.list_backups()}
    finally:
        wrong_schema.unlink(missing_ok=True)


def test_owner_backups_no_uploads_path_leak(local_client: TestClient) -> None:
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    # The page must not surface the absolute uploads/data path of the host.
    assert "C:\\" not in resp.text
    assert "E:\\" not in resp.text


def test_owner_backups_post_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/owner/backups")
    assert resp.status_code == 403
