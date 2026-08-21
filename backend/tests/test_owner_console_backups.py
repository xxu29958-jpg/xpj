"""Read-only Owner Console view of complete dataset backup generations."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

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
    from app.services import dataset_backup_inventory
    from app.services.time_service import now_utc

    if hours_ago is None:
        monkeypatch.setattr(
            dataset_backup_inventory,
            "latest_published_backup_record",
            lambda: None,
        )
        return None
    entry = dataset_backup_inventory.BackupEntry(
        file_name="ticketbox-backup-8c78c277-9e2e-48cd-86a2-7a9087d650a2",
        backup_id="8c78c277-9e2e-48cd-86a2-7a9087d650a2",
        dataset_id="40f0c00b-ef2b-4141-b17c-aebd2da988e2",
        restore_epoch=2,
        size_bytes=4096,
        created_at=now_utc() - timedelta(hours=hours_ago),
        kind="scheduled",
    )
    monkeypatch.setattr(
        dataset_backup_inventory,
        "latest_published_backup_record",
        lambda: entry,
    )
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
    from app.services import dataset_backup_inventory
    from app.services.dataset_backup_contract import read_manifest

    bogus = tmp_path / "ticketbox-backup-a0c5f82d-c95e-452a-8f7a-dba0f0850758"
    bogus.mkdir()
    (bogus / "database.dump").write_bytes(b"database-only")
    monkeypatch.setattr(
        dataset_backup_inventory,
        "_INVENTORY_PATH",
        tmp_path / "backup-inventory.json",
    )

    assert dataset_backup_inventory.list_published_backup_records() == []
    with pytest.raises(AppError):
        read_manifest(bogus, verify_files=True)
    assert bogus.name not in local_client.get("/owner/backups").text


def test_backup_inventory_separates_record_age_from_current_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_backup_inventory

    entry = _stub_latest_backup(monkeypatch, hours_ago=72)
    inventory = dataset_backup_inventory.published_backup_inventory()
    assert inventory.latest is entry
    assert inventory.age_hours == 72
    assert inventory.review_due is True
    assert inventory.integrity_status == "not_rechecked"


def test_ordinary_backup_status_does_not_hash_historical_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import dataset_backup_inventory
    from app.services.time_service import now_utc

    created_at = now_utc().isoformat(timespec="microseconds").replace("+00:00", "Z")
    inventory_path = tmp_path / "backup-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-complete-backup-inventory-v1",
                "generations": [
                    {
                        "generation": "ticketbox-backup-8c78c277-9e2e-48cd-86a2-7a9087d650a2",
                        "backup_id": "8c78c277-9e2e-48cd-86a2-7a9087d650a2",
                        "dataset_id": "40f0c00b-ef2b-4141-b17c-aebd2da988e2",
                        "restore_epoch": 2,
                        "size_bytes": 4096,
                        "created_at": created_at,
                        "kind": "manual",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dataset_backup_inventory, "_INVENTORY_PATH", inventory_path)
    monkeypatch.setattr(
        dataset_backup_inventory,
        "read_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("payload scan")),
    )

    assert len(dataset_backup_inventory.list_published_backup_records()) == 1
    inventory = dataset_backup_inventory.published_backup_inventory()
    assert inventory.integrity_status == "not_rechecked"


def test_backup_inventory_rejects_generation_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import dataset_backup_inventory

    inventory_path = tmp_path / "backup-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-complete-backup-inventory-v1",
                "generations": [
                    {
                        "generation": "ticketbox-backup-8c78c277-9e2e-48cd-86a2-7a9087d650a2",
                        "backup_id": "a0c5f82d-c95e-452a-8f7a-dba0f0850758",
                        "dataset_id": "40f0c00b-ef2b-4141-b17c-aebd2da988e2",
                        "restore_epoch": 2,
                        "size_bytes": 4096,
                        "created_at": "2026-08-21T00:00:00.000000Z",
                        "kind": "manual",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AppError):
        dataset_backup_inventory.list_published_backup_records(
            inventory_path=inventory_path
        )


def test_owner_page_never_leaks_absolute_data_path(local_client: TestClient) -> None:
    response = local_client.get("/owner/backups")
    assert response.status_code == 200
    assert "C:\\" not in response.text
    assert "E:\\" not in response.text
