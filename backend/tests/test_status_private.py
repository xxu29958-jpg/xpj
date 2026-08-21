"""GET /api/status/private 的备份链健康字段(轴6 备份超龄通知数据源)。

独立文件而非并入 test_auth_bootstrap.py:后者已贴近 500 行债务线
(files_over_500 lane 对测试文件同样计数,#49 教训)。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.services import dataset_backup_inventory


def test_private_status_reports_published_backup_record_age(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """有备份时三字段就位,时间戳为 ISO 8601 UTC。

    monkeypatch published inventory 而非铺真实备份文件:本测试钉「route → 响应字段」
    的映射形态；这些字段只表示发布记录时间，不宣称当前 payload 完整。
    """
    entry = dataset_backup_inventory.BackupEntry(
        file_name="ticketbox-backup-82f41001-c8c3-4ec5-a0a6-ab46da0a7900",
        backup_id="82f41001-c8c3-4ec5-a0a6-ab46da0a7900",
        dataset_id="f71cfb0f-1982-48b8-ae92-e4e1f63bd62f",
        restore_epoch=0,
        size_bytes=1024,
        created_at=datetime(2026, 6, 13, 16, 0, 0, tzinfo=UTC),
        kind="scheduled",
    )
    monkeypatch.setattr(
        dataset_backup_inventory,
        "published_backup_inventory",
        lambda: dataset_backup_inventory.PublishedBackupInventory(
            latest=entry,
            age_hours=3,
            review_due=False,
            integrity_status="not_rechecked",
        ),
    )
    body = client.get("/api/status/private", headers=identity.app_headers).json()
    assert body["latest_backup_at"] == "2026-06-13T16:00:00+00:00"
    assert body["backup_age_hours"] == 3
    assert body["backup_stale"] is False
    # 公网 tunnel 端点红线:暴露时间戳/小时数/stale,不暴露备份文件名/目录。
    assert entry.file_name not in body.values()


def test_private_status_reports_missing_backup_as_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """无任何备份 = 链断:latest/age 为 None,stale 必须为 True(不许装健康)。"""
    monkeypatch.setattr(
        dataset_backup_inventory,
        "published_backup_inventory",
        lambda: dataset_backup_inventory.PublishedBackupInventory(
            latest=None,
            age_hours=None,
            review_due=True,
            integrity_status="absent",
        ),
    )
    body = client.get("/api/status/private", headers=identity.app_headers).json()
    assert body["latest_backup_at"] is None
    assert body["backup_age_hours"] is None
    assert body["backup_stale"] is True


def test_private_status_degrades_published_backup_inventory_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """备份探测异常不能打挂私有状态;保守判 stale,等待客户端提醒。"""

    def fail_backup_inventory() -> dataset_backup_inventory.PublishedBackupInventory:
        raise RuntimeError("pg_restore exploded")

    monkeypatch.setattr(
        dataset_backup_inventory,
        "published_backup_inventory",
        fail_backup_inventory,
    )
    response = client.get("/api/status/private", headers=identity.app_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["latest_backup_at"] is None
    assert body["backup_age_hours"] is None
    assert body["backup_stale"] is True
    assert "pg_restore exploded" not in response.text
