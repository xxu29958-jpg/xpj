"""Scheduled revoked-device cleanup wiring."""

from __future__ import annotations

import pytest

from app.config import reset_settings_cache
from app.services.device_cleanup_scheduler import start_device_cleanup_scheduler


def test_device_cleanup_scheduler_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVICE_CLEANUP_AUTO_ENABLED", raising=False)
    reset_settings_cache()
    try:
        scheduler = start_device_cleanup_scheduler()
        assert scheduler.enabled is False
        assert scheduler.thread is None
    finally:
        reset_settings_cache()


def test_device_cleanup_scheduler_starts_when_enabled(
    monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    monkeypatch.setenv("DEVICE_CLEANUP_AUTO_ENABLED", "true")
    monkeypatch.setenv("DEVICE_CLEANUP_DAILY_AT", "04:10")
    monkeypatch.setenv("DEVICE_CLEANUP_TIMEZONE", "Asia/Shanghai")
    reset_settings_cache()
    scheduler = start_device_cleanup_scheduler()
    try:
        assert scheduler.enabled is True
        assert scheduler.thread is not None
        assert scheduler.thread.is_alive()
    finally:
        scheduler.stop()
        reset_settings_cache()


def test_run_cleanup_once_uses_one_global_device_lifecycle_sweep(
    monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    from app.services import device_cleanup_scheduler as sched
    from app.services.admin_service._devices import DeviceCleanupResult

    calls = 0

    def fake_cleanup(db, **kwargs):  # noqa: ANN001, ANN003
        nonlocal calls
        calls += 1
        assert "tenant_id" not in kwargs
        return DeviceCleanupResult(
            retention_days=0,
            scanned=3,
            deleted_devices=2,
            deleted_tokens=0,
            deleted_upload_links=0,
        )

    monkeypatch.setattr(sched, "cleanup_revoked_devices", fake_cleanup)

    scanned, deleted = sched._run_cleanup_once()

    assert calls == 1
    assert scanned == 3
    assert deleted == 2


def test_device_cleanup_scheduler_invalid_config_noops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVICE_CLEANUP_AUTO_ENABLED", "true")
    monkeypatch.setenv("DEVICE_CLEANUP_DAILY_AT", "not-a-time")
    reset_settings_cache()
    try:
        scheduler = start_device_cleanup_scheduler()
        assert scheduler.enabled is False
        assert scheduler.config_error == "invalid_config"
    finally:
        reset_settings_cache()
