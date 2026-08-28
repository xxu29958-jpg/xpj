"""Retirement contract for the removed backup/restore product surface."""

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


def test_owner_backups_surface_is_retired(local_client: TestClient) -> None:
    assert local_client.get("/owner/backups").status_code == 404
    assert local_client.post("/owner/backups").status_code == 404


def test_owner_home_has_no_retired_backup_promise_or_entry(local_client: TestClient) -> None:
    response = local_client.get("/owner")
    assert response.status_code == 200
    assert "/owner/backups" not in response.text
    assert "请从桌面 Manager 发起备份" not in response.text
    assert "数据库备份" not in response.text
    assert "最近备份" not in response.text


def test_frozen_shipment_excludes_retired_dataset_mutation_owners() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    spec = (backend_root / "packaging" / "ticketbox-backend.spec").read_text(encoding="utf-8")
    release_config = json.loads(
        (backend_root / "packaging" / "windows-release-config.json").read_text(encoding="utf-8")
    )

    assert '"_dataset_backup_action.py"' not in spec
    assert '"_dataset_restore_action.py"' not in spec
    assert "retired_dataset_mutation_modules" in spec
    for retired_module in (
        "app.dataset_maintenance_cli",
        "app.database._managed_schema_upgrade",
        "app.services.backup_job_lease",
        "app.services.postgres_backup_adapter",
        "app.services.postgres_backup_validation_service",
    ):
        assert retired_module in spec
    launch = (backend_root / "packaging" / "launch.py").read_text(encoding="utf-8")
    setup = (backend_root / "scripts" / "setup_backend.ps1").read_text(encoding="utf-8")
    assert "--managed-schema-upgrade" not in launch
    assert "files the backend *creates* (uploads, .env, backups)" not in launch
    assert "Owner Console settings .env, PostgreSQL backups" not in launch
    assert 'Join-Path $BackendRoot "backups"' not in setup
    for retired_timeout in (
        "dataset_backup_helper_timeout_ms",
        "dataset_restore_helper_timeout_ms",
        "dataset_payload_verification_timeout_ms",
        "complete_dataset_cleanup_reserve_ms",
        "complete_dataset_backup_timeout_ms",
        "complete_dataset_restore_timeout_ms",
    ):
        assert retired_timeout not in release_config


def test_maintained_docs_do_not_promise_the_retired_backup_record_entry() -> None:
    root = Path(__file__).resolve().parents[2]
    maintained = (
        root / "docs" / "runbook" / "WINDOWS_BACKUP_TASK.md",
        root / "docs" / "runbook" / "GRAY_ACCEPTANCE_EXECUTION.md",
        root / "docs" / "runbook" / "WINDOWS_SERVICE_RUNBOOK.md",
        root / "docs" / "runbook" / "POSTGRES_MIGRATION.md",
        root / "docs" / "architecture" / "SECURITY.md",
        root / "backend" / "README.md",
        root / "backend" / "packaging" / "README.md",
        root / "backend" / "packaging" / "build_pg_bundle.ps1",
        root / "scripts" / "maintenance_ticketbox.ps1",
        root / "scripts" / "check_selfuse_health.ps1",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in maintained)

    assert "查看备份记录" not in combined
    assert "open_backups" not in combined
    assert "windows_dataset_backup.ps1" not in combined
    assert "windows_dataset_restore.ps1" not in combined
    assert "完整 backup generation 的隔离恢复" not in combined
    assert "正式 Windows 安装只通过桌面管理器执行备份和恢复" not in combined
    assert "先在已安装 Manager 中完成完整数据集备份" not in combined
    assert "recent backup exists" not in combined
    assert "计划备份（backup_service）" not in combined
    assert "恢复 / 备份校验" not in combined
    assert "创建 `data`、`uploads`、`logs`、`backups` 目录" not in combined


def test_incomplete_generation_is_not_listed(
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


def test_future_backup_record_is_stale_without_a_negative_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_backup_inventory

    entry = _stub_latest_backup(monkeypatch, hours_ago=-1)
    inventory = dataset_backup_inventory.published_backup_inventory()

    assert inventory.latest is entry
    assert inventory.age_hours is None
    assert inventory.review_due is True
    assert inventory.age_status == "future"


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
        dataset_backup_inventory.list_published_backup_records(inventory_path=inventory_path)
