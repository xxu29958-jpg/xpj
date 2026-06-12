"""GET /api/status/private 的备份链健康字段(轴6 备份超龄通知数据源)。

独立文件而非并入 test_auth_bootstrap.py:后者已贴近 500 行债务线
(files_over_500 lane 对测试文件同样计数,#49 教训)。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.services import backup_service


def test_private_status_reports_backup_health(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """有备份时三字段就位,时间戳为 ISO 8601 UTC。

    monkeypatch backup_health 而非铺真实备份文件:本测试钉「route → 响应字段」的
    映射形态;48h stale 判定本身在 backup_service 测试里钉。
    """
    entry = backup_service.BackupEntry(
        file_name="ticketbox-20260613-160000.dump",
        size_bytes=1024,
        created_at=datetime(2026, 6, 13, 16, 0, 0, tzinfo=UTC),
        kind="scheduled",
    )
    monkeypatch.setattr(
        backup_service,
        "backup_health",
        lambda: backup_service.BackupHealth(latest=entry, age_hours=3, stale=False),
    )
    body = client.get("/api/status/private", headers=identity.app_headers).json()
    assert body["latest_backup_at"] == "2026-06-13T16:00:00+00:00"
    assert body["backup_age_hours"] == 3
    assert body["backup_stale"] is False
    # 公网 tunnel 端点红线:暴露时间戳/小时数/stale,不暴露备份文件名/目录。
    assert "ticketbox-20260613-160000.dump" not in body.values()


def test_private_status_reports_missing_backup_as_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """无任何备份 = 链断:latest/age 为 None,stale 必须为 True(不许装健康)。"""
    monkeypatch.setattr(
        backup_service,
        "backup_health",
        lambda: backup_service.BackupHealth(latest=None, age_hours=None, stale=True),
    )
    body = client.get("/api/status/private", headers=identity.app_headers).json()
    assert body["latest_backup_at"] is None
    assert body["backup_age_hours"] is None
    assert body["backup_stale"] is True


def test_private_status_degrades_backup_health_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """备份探测异常不能打挂私有状态;保守判 stale,等待客户端提醒。"""

    def fail_backup_health() -> backup_service.BackupHealth:
        raise RuntimeError("pg_restore exploded")

    monkeypatch.setattr(backup_service, "backup_health", fail_backup_health)
    response = client.get("/api/status/private", headers=identity.app_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["latest_backup_at"] is None
    assert body["backup_age_hours"] is None
    assert body["backup_stale"] is True
    assert "pg_restore exploded" not in response.text
