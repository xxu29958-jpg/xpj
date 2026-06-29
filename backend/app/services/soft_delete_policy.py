"""Soft-delete retention policy.

ADR-0038 的原始 undo banner 仍是 5 分钟语义；ADR-0051 回收站把“显式进入回收站后
可恢复”解耦为天级保留。默认撤销入口继续用短窗，回收站入口和 purge 用天级窗口，
避免清理任务在用户还有机会从回收站恢复时提前硬删。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.config import get_settings
from app.services.time_service import ensure_utc, now_utc

# ADR-0038 undo banner 的服务端短窗。保持常量名兼容既有测试/调用点。
SOFT_DELETE_RETENTION_MINUTES = 5
SOFT_DELETE_RETENTION = timedelta(minutes=SOFT_DELETE_RETENTION_MINUTES)


def is_within_undo_window(deleted_at: datetime | None) -> bool:
    """Soft-deleted row is still restorable from the short undo banner."""
    return _is_within_window(deleted_at, SOFT_DELETE_RETENTION)


def recycle_bin_retention_days() -> int:
    return max(1, int(get_settings().recycle_bin_retention_days))


def recycle_bin_retention_delta() -> timedelta:
    return timedelta(days=recycle_bin_retention_days())


def recycle_bin_retention_label() -> str:
    return f"{recycle_bin_retention_days()} 天内可恢复"


def is_within_recycle_bin_window(deleted_at: datetime | None) -> bool:
    """Soft-deleted row is still available from the explicit recycle bin."""
    return _is_within_window(deleted_at, recycle_bin_retention_delta())


def _is_within_window(deleted_at: datetime | None, window: timedelta) -> bool:
    aware = ensure_utc(deleted_at)
    if aware is None:
        return False
    return now_utc() - aware <= window
