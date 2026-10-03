"""Closed choices for existing upload and maintenance services."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class UploadSettingsProjection:
    max_upload_size_mb: int = 10
    upload_link_ttl_days: int = 90
    upload_link_default_daily_byte_budget: int = 200 * 1024 * 1024
    upload_link_default_per_remote_interval_seconds: int = 2


@dataclass(frozen=True)
class MaintenanceSettingsProjection:
    learning_cleanup_auto_enabled: bool = False
    learning_cleanup_daily_at: str = "03:30"
    learning_cleanup_timezone: str = "Asia/Shanghai"
    budget_advisor_audit_cleanup_auto_enabled: bool = False
    budget_advisor_audit_cleanup_daily_at: str = "03:45"
    budget_advisor_audit_cleanup_timezone: str = "Asia/Shanghai"
    budget_advisor_audit_retention_days: int = 180
    device_cleanup_auto_enabled: bool = False
    device_cleanup_daily_at: str = "04:10"
    device_cleanup_timezone: str = "Asia/Shanghai"
    device_cleanup_retention_days: int = 180
    soft_delete_purge_auto_enabled: bool = False
    recycle_bin_retention_days: int = 30


INTEGER_LIMITS = {
    "max_upload_size_mb": (1, 1024),
    "upload_link_ttl_days": (1, 3650),
    "upload_link_default_daily_byte_budget": (0, 1048576 * 1024 * 1024),
    "upload_link_default_per_remote_interval_seconds": (0, 86400),
    "budget_advisor_audit_retention_days": (0, 36500),
    "device_cleanup_retention_days": (0, 36500),
    "recycle_bin_retention_days": (1, 36500),
}


def operations_payload(value: UploadSettingsProjection | MaintenanceSettingsProjection) -> dict[str, object]:
    payload = asdict(value)
    for name, item in payload.items():
        if name in INTEGER_LIMITS:
            lower, upper = INTEGER_LIMITS[name]
            if type(item) is not int or not lower <= item <= upper:
                raise ValueError(f"invalid runtime setting: {name}")
        elif name.endswith("_enabled"):
            if type(item) is not bool:
                raise ValueError(f"invalid runtime setting: {name}")
        elif name.endswith("_daily_at"):
            parsed = time.fromisoformat(item)
            if parsed.strftime("%H:%M") != item:
                raise ValueError(f"invalid daily time: {name}")
        else:
            if not isinstance(item, str) or len(item) > 64:
                raise ValueError(f"invalid timezone: {name}")
            ZoneInfo(item)
    return payload


def _environment_values(defaults: UploadSettingsProjection | MaintenanceSettingsProjection) -> dict[str, object]:
    values = asdict(defaults)
    for name, default in values.items():
        raw = os.getenv(name.upper(), str(default))
        if isinstance(default, bool):
            values[name] = raw.strip().lower() in {"1", "true", "yes", "on"}
        elif isinstance(default, int):
            values[name] = int(raw)
        else:
            values[name] = raw.strip() or default
    return values


def resolve_upload_settings(saved: UploadSettingsProjection | None) -> UploadSettingsProjection:
    if saved is not None:
        return saved
    values = _environment_values(UploadSettingsProjection())
    values["upload_link_ttl_days"] = max(1, values["upload_link_ttl_days"])
    return UploadSettingsProjection(**values)


def resolve_maintenance_settings(saved: MaintenanceSettingsProjection | None) -> MaintenanceSettingsProjection:
    if saved is not None:
        return saved
    values = _environment_values(MaintenanceSettingsProjection())
    values["device_cleanup_retention_days"] = max(0, values["device_cleanup_retention_days"])
    values["recycle_bin_retention_days"] = max(1, values["recycle_bin_retention_days"])
    return MaintenanceSettingsProjection(**values)
