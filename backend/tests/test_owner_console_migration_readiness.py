"""Tests for /owner/migration-readiness."""

from __future__ import annotations

from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local
from app.services import backup_service
from app.services.migration_readiness_service import build_v1_migration_readiness_report

_requires_file_sqlite = pytest.mark.file_backed_only


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def _delete_backup(file_name: str | None) -> None:
    if not file_name:
        return
    path = backup_service._backup_dir() / file_name  # noqa: SLF001
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return parser.text()


def test_owner_migration_readiness_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/migration-readiness")

    assert resp.status_code == 200
    assert "v1.0 迁移预检" in resp.text
    assert "检查项" in resp.text
    assert "创建 pre-v1.0 备份并重新检查" in resp.text


def test_owner_migration_readiness_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/owner/migration-readiness")

    assert resp.status_code == 403


def test_owner_migration_readiness_post_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/owner/migration-readiness/pre-v1-backup")

    assert resp.status_code == 403


@_requires_file_sqlite
def test_owner_migration_readiness_create_pre_v1_backup(local_client: TestClient) -> None:
    before = {entry.file_name for entry in backup_service.list_backups()}

    resp = local_client.post("/owner/migration-readiness/pre-v1-backup")

    after_entries = backup_service.list_backups()
    created = [
        entry.file_name
        for entry in after_entries
        if entry.file_name not in before and entry.kind == "pre-v1.0"
    ]
    try:
        assert resp.status_code == 200
        assert len(created) == 1
        assert created[0] in resp.text
        assert "已创建 pre-v1.0 回滚备份" in resp.text
    finally:
        for file_name in created:
            _delete_backup(file_name)


@_requires_file_sqlite
def test_owner_migration_readiness_does_not_trust_invalid_pre_v1_backup(
    local_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del local_client
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    (tmp_path / "ticketbox-pre-v1.0-29991231-235959.db").write_bytes(b"not sqlite")

    report = build_v1_migration_readiness_report(create_backup=False)
    backup_check = next(check for check in report.checks if check.code == "backup_available")

    assert report.latest_backup is None
    assert backup_check.status == "error"


def test_owner_migration_readiness_does_not_leak_sensitive_values(
    local_client: TestClient,
) -> None:
    resp = local_client.get("/owner/migration-readiness")

    assert resp.status_code == 200
    visible_text = _visible_text(resp.text)
    assert "C:\\" not in visible_text
    assert "E:\\" not in visible_text
    assert "/data/" not in visible_text
    assert "Authorization" not in visible_text
    assert "Bearer" not in visible_text
    assert "token" not in visible_text.lower()
    assert "restore" not in visible_text.lower()
