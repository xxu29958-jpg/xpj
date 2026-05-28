"""Budget advisor audit cleanup scheduler wiring."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.budget_advisor_audit_cleanup_scheduler import (
    start_budget_advisor_audit_cleanup_scheduler,
)


def test_budget_advisor_audit_cleanup_scheduler_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BUDGET_ADVISOR_AUDIT_CLEANUP_AUTO_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        scheduler = start_budget_advisor_audit_cleanup_scheduler()
        assert scheduler.enabled is False
        assert scheduler.thread is None
    finally:
        get_settings.cache_clear()


def test_budget_advisor_audit_cleanup_scheduler_starts_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_AUDIT_CLEANUP_AUTO_ENABLED", "true")
    monkeypatch.setenv("BUDGET_ADVISOR_AUDIT_CLEANUP_DAILY_AT", "03:45")
    monkeypatch.setenv("BUDGET_ADVISOR_AUDIT_CLEANUP_TIMEZONE", "Asia/Shanghai")
    get_settings.cache_clear()
    scheduler = start_budget_advisor_audit_cleanup_scheduler()
    try:
        assert scheduler.enabled is True
        assert scheduler.thread is not None
        assert scheduler.thread.is_alive()
    finally:
        scheduler.stop()
        get_settings.cache_clear()


def test_budget_advisor_audit_cleanup_scheduler_invalid_config_noops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUDGET_ADVISOR_AUDIT_CLEANUP_AUTO_ENABLED", "true")
    monkeypatch.setenv("BUDGET_ADVISOR_AUDIT_CLEANUP_DAILY_AT", "not-a-time")
    get_settings.cache_clear()
    try:
        scheduler = start_budget_advisor_audit_cleanup_scheduler()
        assert scheduler.enabled is False
        assert scheduler.config_error == "invalid_config"
    finally:
        get_settings.cache_clear()
