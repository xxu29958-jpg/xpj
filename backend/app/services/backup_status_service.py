"""Lightweight backup-status caliber for read-heavy status surfaces.

Split out of ``backup_service`` (PR #253 R4, 守 files_over_500 债线):
the Owner Console restore picker keeps ``backup_service.list_backups()``
(every-dump ``pg_restore --list`` validation); the /web overview + dashboard
backup card use ``latest_backup_lightweight()`` from here — newest-first,
one verdict per file per process, tri-state about tool failures.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.services.backup_service import _PREFIX, _SUFFIX, BackupEntry, _backup_dir, _classify
from app.services.postgres_backup_validation_service import (
    PostgresBackupToolError,
    PostgresBackupValidationError,
    validate_postgres_backup_file,
)

# 进程内缓存: (file_name, mtime_ns, size) -> ``pg_restore --list`` 验证结果
# (PR #253 R2 bot-P1)。只原地增删 (dict[key]=value / clear), 不整体重绑。
_lightweight_backup_validation: dict[tuple[str, int, int], bool] = {}

# 工具熔断 (PR #253 R6-1): pg_restore 持续不可用时, 记一次「不可用时刻」,
# TTL 内直接按 unverified 呈现, 不再每请求逐文件重试 (30 个保留 dump × 60s
# 超时 ≈ 每请求 30 分钟); TTL 过后放行一次探测, 拿到真实结论即自动复位。
# dict 单键原地改写, 与上面的验证缓存同一进程内状态惯例。
_TOOL_OUTAGE_TTL_SECONDS = 60.0
_tool_outage: dict[str, float] = {}


def _tool_outage_active() -> bool:
    since = _tool_outage.get("since")
    return since is not None and (time.monotonic() - since) < _TOOL_OUTAGE_TTL_SECONDS


@dataclass(frozen=True)
class LightweightBackupStatus:
    """三态备份状态 (PR #253 R5): 不谎称可用, 也不谎称没有。

    - ``valid``: entry = 最新可恢复 dump (验证通过);
    - ``none``: 没有 dump 文件, 或全部归档畸形 → 「无可恢复备份」;
    - ``unverified``: 有 dump 文件但验证工具暂时失败 (pg_restore 缺失/超时),
      无法判定 → 「检测到备份文件, 尚未验证」。
    """

    entry: BackupEntry | None
    state: str  # "valid" / "none" / "unverified"


def _validate_dump_for_status(path: Path) -> bool | None:
    """三态验证 (PR #253 R4-3): True=可恢复; False=归档畸形 (可缓存);
    None=工具暂时失败 (pg_restore 缺失/启动失败/超时——不可当 invalid 缓存)。"""
    try:
        validate_postgres_backup_file(path)
    except PostgresBackupToolError:
        return None
    except PostgresBackupValidationError:
        return False
    return True


def _backup_entry(path: Path, stat: os.stat_result) -> BackupEntry:
    return BackupEntry(
        file_name=path.name,
        size_bytes=int(stat.st_size),
        created_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
        kind=_classify(path.name),
    )


def latest_backup_lightweight() -> LightweightBackupStatus:
    """Newest-first validation with tri-state presentation + tool circuit.

    Same "newest valid" semantics as ``backup_service.latest_backup()`` (PR
    #253 R3), memoized per ``(name, mtime_ns, size)`` so steady state spawns no
    subprocess and each file is validated at most once per process. A tool
    failure trips a short circuit (R6-1): the request returns ``unverified``
    immediately and later requests within ``_TOOL_OUTAGE_TTL_SECONDS`` skip the
    tool entirely; the first probe after the TTL resets the breaker on any real
    verdict. Restore/health flows keep the every-dump fully validated caliber.
    """
    candidates: list[tuple[Path, os.stat_result]] = []
    for path in _backup_dir().glob(f"{_PREFIX}*{_SUFFIX}"):
        try:
            if path.is_file():
                candidates.append((path, path.stat()))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[1].st_mtime, reverse=True)
    if _tool_outage_active():
        # 熔断期: 不逐文件重试工具, 按「有文件但未验证」呈现 (R6-1)。
        return LightweightBackupStatus(
            entry=None, state="unverified" if candidates else "none"
        )
    for path, stat in candidates:
        cache_key = (path.name, stat.st_mtime_ns, int(stat.st_size))
        valid = _lightweight_backup_validation.get(cache_key)
        if valid is None:
            if len(_lightweight_backup_validation) >= 64:
                _lightweight_backup_validation.clear()  # 键只随新 dump 出现, 清空=下次重验
            valid = _validate_dump_for_status(path)
            if valid is None:
                # 首次工具失败即熔断: 本请求不再扫更旧的文件, TTL 后自动重探。
                _tool_outage["since"] = time.monotonic()
                return LightweightBackupStatus(entry=None, state="unverified")
            _tool_outage.pop("since", None)  # 拿到真实结论 = 工具可用, 自动复位
            _lightweight_backup_validation[cache_key] = valid
        if valid:
            return LightweightBackupStatus(entry=_backup_entry(path, stat), state="valid")
    return LightweightBackupStatus(entry=None, state="none")
