from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import SimpleNamespace

import pytest

from app import config
from app.errors import AppError
from app.services import operations_settings_service as operations
from app.services import runtime_maintenance_schedule as schedule
from app.services import runtime_settings_service as runtime
from app.services import runtime_settings_store as store
from app.services.session_lifecycle_service import upload_link_expires_at
from app.services.upload_link_throttle_service import resolve_limits


@pytest.fixture
def operations_file(tmp_path, monkeypatch):
    target = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(config, "RUNTIME_SETTINGS_PATH", target)
    monkeypatch.setattr(config, "_RUNTIME_SETTINGS_SERVICE_OWNED", False)
    monkeypatch.setattr(runtime, "_SETTINGS_PATH", target)
    monkeypatch.setattr(runtime, "_SERVICE_OWNED", False)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    config.reset_settings_cache()
    yield target
    config.reset_settings_cache()


def test_saved_upload_defaults_reach_existing_limit_and_expiry_consumers(operations_file):
    operations.save_uploads({"max_upload_size_mb": "12", "upload_link_ttl_days": "45", "daily_budget_mb": "12.5",
                            "upload_link_default_per_remote_interval_seconds": "7"})
    config.reset_settings_cache()
    issued = datetime(2026, 10, 3, tzinfo=UTC)
    assert config.get_settings().max_upload_size_bytes == 12 * 1024 * 1024
    assert upload_link_expires_at(issued) == issued + timedelta(days=45)
    defaults = resolve_limits(SimpleNamespace(daily_byte_budget=None, per_remote_min_interval_seconds=0))
    assert defaults.daily_byte_budget == 13107200 and defaults.per_remote_min_interval_seconds == 7
    explicit = resolve_limits(SimpleNamespace(daily_byte_budget=1000, per_remote_min_interval_seconds=9))
    assert explicit.daily_byte_budget == 1000 and explicit.per_remote_min_interval_seconds == 9


def test_cleanup_requires_acknowledgement_and_keeps_the_saved_upload_choices(operations_file):
    runtime.update_public_base_url("https://upload.example")
    form = operations.maintenance_form()
    form.update(learning_cleanup_auto_enabled=True, learning_cleanup_daily_at="05:10",
                budget_advisor_audit_retention_days="0", device_cleanup_retention_days="7")
    before = operations_file.read_bytes()
    with pytest.raises(AppError, match="确认清理影响"):
        operations.save_maintenance(form, confirmed=False)
    assert operations_file.read_bytes() == before
    operations.save_maintenance(form, confirmed=True)
    config.reset_settings_cache()
    saved = config.get_settings()
    assert saved.learning_cleanup_auto_enabled is True and saved.learning_cleanup_daily_at == "05:10"
    assert saved.budget_advisor_audit_retention_days == 0 and saved.device_cleanup_retention_days == 7
    assert saved.public_base_url == "https://upload.example"
    form.update(learning_cleanup_auto_enabled=False, recycle_bin_retention_days="1")
    with pytest.raises(AppError, match="恢复窗口"):
        operations.save_maintenance(form, confirmed=False)
    form["recycle_bin_retention_days"] = str(saved.recycle_bin_retention_days)
    operations.save_maintenance(form, confirmed=False)
    assert config.get_settings().learning_cleanup_auto_enabled is False


@pytest.mark.parametrize("change", [
    {"device_cleanup_retention_days": "-1"}, {"learning_cleanup_daily_at": "25:00"},
    {"learning_cleanup_timezone": "wrong/zone"}, {"recycle_bin_retention_days": "0"},
])
def test_invalid_maintenance_choice_preserves_saved_settings(operations_file, change):
    form = operations.maintenance_form()
    operations.save_maintenance(form, confirmed=True)
    before = operations_file.read_bytes()
    with pytest.raises(AppError):
        operations.save_maintenance({**form, **change}, confirmed=True)
    assert operations_file.read_bytes() == before


def test_operations_publication_failure_preserves_effective_choices(operations_file, monkeypatch):
    operations.save_uploads(operations.upload_form())
    before = operations_file.read_bytes()
    original = config.get_settings().upload_link_ttl_days
    def denied(*args, **kwargs):
        raise OSError("publication denied")
    monkeypatch.setattr(store, "write_protected_file_replace", denied)
    with pytest.raises(AppError, match="原设置仍保留"):
        operations.save_uploads({**operations.upload_form(), "upload_link_ttl_days": "365"})
    assert operations_file.read_bytes() == before
    assert config.get_settings().upload_link_ttl_days == original


def test_daily_plan_follows_enable_and_time_change_before_any_cleanup(monkeypatch):
    choices = SimpleNamespace(learning_cleanup_auto_enabled=False, learning_cleanup_daily_at="00:01", learning_cleanup_timezone="UTC")
    current = datetime(2026, 10, 3, tzinfo=UTC)
    waits = []
    class Clock:
        @staticmethod
        def now(tz):
            return current.astimezone(tz)
    class Stop:
        def is_set(self):
            return False
        def wait(self, seconds):
            nonlocal current
            waits.append(seconds)
            current += timedelta(seconds=seconds)
            if len(waits) == 1:
                choices.learning_cleanup_auto_enabled = True
            if len(waits) == 2:
                choices.learning_cleanup_daily_at = "00:02"
            return len(waits) > 5
    monkeypatch.setattr(schedule, "datetime", Clock)
    monkeypatch.setattr(schedule, "get_settings", lambda: choices)
    assert schedule.wait_for_daily_run(Stop(), "learning_cleanup") == datetime(2026, 10, 3, 0, 2, tzinfo=UTC)
    assert all(0 < delay <= 30 for delay in waits)


@pytest.mark.parametrize("disable_before_due", [False, True])
def test_interval_plan_runs_only_after_enabled_interval_and_cancels_when_disabled(monkeypatch, disable_before_due):
    choices = SimpleNamespace(soft_delete_purge_auto_enabled=False)
    ticks = 0
    seconds = 0
    class Stop:
        def is_set(self):
            return False
        def wait(self, delay):
            nonlocal ticks, seconds
            ticks += 1
            seconds += delay
            if ticks == 2:
                choices.soft_delete_purge_auto_enabled = True
            if ticks == 3 and disable_before_due:
                choices.soft_delete_purge_auto_enabled = False
            return ticks == 6
    monkeypatch.setattr(schedule, "get_settings", lambda: choices)
    monkeypatch.setattr(schedule, "monotonic", lambda: seconds)
    assert schedule.wait_for_interval_run(Stop(), "soft_delete_purge_auto_enabled", 60) is not disable_before_due
    assert seconds >= 120


@pytest.mark.parametrize("module_name,flag", [
    ("learning_cleanup", "LEARNING_CLEANUP_AUTO_ENABLED"),
    ("budget_advisor_audit_cleanup", "BUDGET_ADVISOR_AUDIT_CLEANUP_AUTO_ENABLED"),
    ("device_cleanup", "DEVICE_CLEANUP_AUTO_ENABLED"),
    ("soft_delete_purge", "SOFT_DELETE_PURGE_AUTO_ENABLED"),
])
def test_disabled_workers_can_follow_later_owner_choices_without_restart(tmp_path, monkeypatch, module_name, flag):
    monkeypatch.setattr(config, "RUNTIME_SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config, "_RUNTIME_SETTINGS_SERVICE_OWNED", False)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv(flag, "false")
    config.reset_settings_cache()
    module = import_module(f"app.services.{module_name}_scheduler")
    worker = getattr(module, f"start_{module_name}_scheduler")()
    try:
        assert worker is not None and worker.thread is not None and worker.thread.is_alive()
    finally:
        if worker is not None:
            worker.stop()
        config.reset_settings_cache()
