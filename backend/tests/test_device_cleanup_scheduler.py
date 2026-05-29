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


def test_run_cleanup_once_continues_past_failing_ledger(
    monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """A ledger whose cleanup raises is logged and skipped; the sweep still
    processes every later ledger instead of aborting (ENGINEERING_RULES §7)."""
    from app.database import SessionLocal
    from app.models import Account, Ledger
    from app.services import device_cleanup_scheduler as sched
    from app.services.admin_service._devices import DeviceCleanupResult

    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        db.add(Ledger(ledger_id="zzz_ledger", name="zzz", owner_account_id=owner.id))
        db.commit()

    seen: list[str] = []

    def fake_cleanup(db, *, tenant_id, **kwargs):  # noqa: ANN001, ANN003
        seen.append(tenant_id)
        if len(seen) == 1:
            raise RuntimeError("simulated per-ledger cleanup failure")
        return DeviceCleanupResult(
            retention_days=0,
            scanned=0,
            deleted_devices=1,
            deleted_tokens=0,
            deleted_upload_links=0,
        )

    monkeypatch.setattr(sched, "cleanup_revoked_devices", fake_cleanup)

    # Must not raise; the first ledger fails and is skipped.
    scanned, deleted = sched._run_cleanup_once()

    assert len(seen) >= 2  # zzz_ledger guarantees a second ledger past the failure
    assert scanned == len(seen) - 1
    assert deleted == scanned


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
