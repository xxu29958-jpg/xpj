"""Read-only Owner Console view of complete dataset backup generations."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError
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
        monkeypatch.setattr(backup_service, "latest_published_backup_record", lambda: None)
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
    monkeypatch.setattr(backup_service, "latest_published_backup_record", lambda: entry)
    return entry


def test_owner_backups_page_is_read_only_complete_generation_view(
    local_client: TestClient,
) -> None:
    response = local_client.get("/owner/backups")
    assert response.status_code == 200
    assert "备份记录" in response.text
    assert "数据库、原始票据附件、数据集身份和校验清单" in response.text
    assert "当前字节未复检" in response.text
    assert "不会显示为有效备份" not in response.text
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

    assert backup_service.list_published_backup_records() == []
    with pytest.raises(AppError):
        backup_service.read_manifest(bogus, verify_files=True)
    assert bogus.name not in local_client.get("/owner/backups").text


def test_backup_inventory_separates_record_age_from_current_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import backup_service

    entry = _stub_latest_backup(monkeypatch, hours_ago=72)
    inventory = backup_service.published_backup_inventory()
    assert inventory.latest is entry
    assert inventory.age_hours == 72
    assert inventory.review_due is True
    assert inventory.integrity_status == "not_rechecked"


def test_ordinary_backup_status_does_not_hash_historical_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import backup_service
    from app.services.time_service import now_utc

    generation = tmp_path / "ticketbox-backup-8c78c277-9e2e-48cd-86a2-7a9087d650a2"
    generation.mkdir()
    calls: list[bool] = []

    def read_metadata(_path: Path, *, verify_files: bool):
        calls.append(verify_files)
        return SimpleNamespace(
            backup_id="8c78c277-9e2e-48cd-86a2-7a9087d650a2",
            authority=SimpleNamespace(
                dataset_id="40f0c00b-ef2b-4141-b17c-aebd2da988e2",
                restore_epoch=2,
            ),
            total_size_bytes=4096,
            created_at=now_utc(),
            backup_kind="manual",
        )

    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    monkeypatch.setattr(backup_service, "read_manifest", read_metadata)

    assert len(backup_service.list_published_backup_records()) == 1
    assert calls == [False]
    inventory = backup_service.published_backup_inventory()
    assert inventory.integrity_status == "not_rechecked"


def test_backup_inventory_rejects_directory_manifest_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import backup_service
    from app.services.time_service import now_utc

    generation = tmp_path / "ticketbox-backup-8c78c277-9e2e-48cd-86a2-7a9087d650a2"
    generation.mkdir()
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    monkeypatch.setattr(
        backup_service,
        "read_manifest",
        lambda *_args, **_kwargs: SimpleNamespace(
            backup_id="a0c5f82d-c95e-452a-8f7a-dba0f0850758",
            authority=SimpleNamespace(
                dataset_id="40f0c00b-ef2b-4141-b17c-aebd2da988e2",
                restore_epoch=2,
            ),
            total_size_bytes=4096,
            created_at=now_utc(),
            backup_kind="manual",
        ),
    )

    assert backup_service.list_published_backup_records() == []


def test_owner_page_never_leaks_absolute_data_path(local_client: TestClient) -> None:
    response = local_client.get("/owner/backups")
    assert response.status_code == 200
    assert "C:\\" not in response.text
    assert "E:\\" not in response.text
