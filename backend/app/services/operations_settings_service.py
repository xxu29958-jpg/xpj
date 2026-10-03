"""Owner forms for upload defaults and the existing maintenance workers."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfoNotFoundError

from app.config import get_settings
from app.services import runtime_settings_service as runtime
from app.services.budget_advisor_audit_cleanup_scheduler import budget_advisor_audit_cleanup_status_snapshot
from app.services.device_cleanup_scheduler import device_cleanup_status_snapshot
from app.services.learning_cleanup_scheduler import learning_cleanup_status_snapshot
from app.services.runtime_operations_settings import (
    INTEGER_LIMITS,
    MaintenanceSettingsProjection,
    UploadSettingsProjection,
    operations_payload,
)
from app.services.runtime_settings_store import RuntimeSettingsMutation
from app.services.soft_delete_purge_scheduler import soft_delete_purge_status_snapshot

_MIB = 1024 * 1024
_RETENTION_LABELS = {
    "budget_advisor_audit_retention_days": "新 AI 调用记录保留天数",
    "device_cleanup_retention_days": "已撤销设备保留天数",
    "recycle_bin_retention_days": "回收站保留天数",
}


def upload_form() -> dict[str, str]:
    settings = get_settings()
    return {
        "max_upload_size_mb": str(settings.max_upload_size_mb),
        "upload_link_ttl_days": str(settings.upload_link_ttl_days),
        "daily_budget_mb": str(Decimal(settings.upload_link_default_daily_byte_budget) / _MIB),
        "upload_link_default_per_remote_interval_seconds": str(settings.upload_link_default_per_remote_interval_seconds),
    }


def save_uploads(form: dict[str, str]) -> None:
    try:
        budget = Decimal(form["daily_budget_mb"]) * _MIB
        if not budget.is_finite() or budget != budget.to_integral_value() or not 0 <= budget <= INTEGER_LIMITS["upload_link_default_daily_byte_budget"][1]:
            raise ValueError("invalid upload budget")
    except (InvalidOperation, ValueError) as exc:
        raise runtime._invalid("每日上传配额须为 0–1048576 MB，可填写小数；0 表示不限额。") from exc
    value = UploadSettingsProjection(
        max_upload_size_mb=runtime._bounded_int(form["max_upload_size_mb"], label="单文件上限", minimum=1, maximum=1024),
        upload_link_ttl_days=runtime._bounded_int(form["upload_link_ttl_days"], label="新链接有效天数", minimum=1, maximum=3650),
        upload_link_default_daily_byte_budget=int(budget),
        upload_link_default_per_remote_interval_seconds=runtime._bounded_int(
            form["upload_link_default_per_remote_interval_seconds"], label="同端上传间隔", minimum=0, maximum=86400),
    )
    runtime.save_runtime_mutation(RuntimeSettingsMutation("uploads", value))


def maintenance_form() -> dict[str, str | bool]:
    settings = get_settings()
    return {name: getattr(settings, name) if isinstance(default, bool) else str(getattr(settings, name))
            for name, default in asdict(MaintenanceSettingsProjection()).items()}


def save_maintenance(form: dict[str, str | bool], *, confirmed: bool) -> None:
    values = dict(form)
    for name, label in _RETENTION_LABELS.items():
        lower, upper = INTEGER_LIMITS[name]
        values[name] = runtime._bounded_int(values[name], label=label, minimum=lower, maximum=upper)
    for name in values:
        if name.endswith(("_daily_at", "_timezone")):
            values[name] = str(values[name]).strip()
    value = MaintenanceSettingsProjection(**values)
    try:
        operations_payload(value)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise runtime._invalid("请检查清理时间和时区：时间使用 HH:MM，时区使用 Asia/Shanghai 等有效名称。") from exc
    settings = get_settings()
    changes_recovery_window = value.recycle_bin_retention_days < settings.recycle_bin_retention_days
    auto_cleanup = any(item for name, item in values.items() if name.endswith("_enabled"))
    if (auto_cleanup or changes_recovery_window) and not confirmed:
        raise runtime._invalid("请先确认清理影响。自动清理会永久删除符合条件的过期数据；缩短回收站期限也会缩短现有记录的恢复窗口。")
    runtime.save_runtime_mutation(RuntimeSettingsMutation("maintenance", value))


def maintenance_status() -> dict[str, object]:
    return {
        "learning_cleanup": learning_cleanup_status_snapshot(),
        "budget_advisor_audit_cleanup": budget_advisor_audit_cleanup_status_snapshot(),
        "device_cleanup": device_cleanup_status_snapshot(),
        "soft_delete_purge": soft_delete_purge_status_snapshot(),
    }
