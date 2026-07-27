"""Lightweight backup-status caliber for read-heavy status surfaces.

Split out of ``backup_service`` (PR #253 R4, 守 files_over_500 债线):
the Owner Console restore picker keeps ``backup_service.list_backups()``
(every-dump ``pg_restore --list`` validation); the /web overview + dashboard
backup card use ``latest_backup_lightweight()`` from here — newest-first,
one verdict per file per process, tri-state about tool failures.
"""

from __future__ import annotations

import os
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


def latest_backup_lightweight() -> BackupEntry | None:
    """Newest VALID dump — a corrupt newest one yields to older valid ones.

    Same "newest valid" semantics as ``backup_service.latest_backup()`` (PR
    #253 R3), but validates candidates newest-first via ``pg_restore --list``,
    memoized per ``(name, mtime_ns, size)``: steady state spawns no subprocess
    and each file is validated at most once per process. A tool outage
    (``_validate_dump_for_status`` → None) is presented as "present but
    unverified" for the newest candidate and is never cached (R4-3).
    Restore/health flows keep the every-dump fully validated caliber.
    """
    candidates: list[tuple[Path, os.stat_result]] = []
    for path in _backup_dir().glob(f"{_PREFIX}*{_SUFFIX}"):
        try:
            if path.is_file():
                candidates.append((path, path.stat()))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[1].st_mtime, reverse=True)
    for path, stat in candidates:
        cache_key = (path.name, stat.st_mtime_ns, int(stat.st_size))
        valid = _lightweight_backup_validation.get(cache_key)
        if valid is None:
            if len(_lightweight_backup_validation) >= 64:
                _lightweight_backup_validation.clear()  # 键只随新 dump 出现, 清空=下次重验
            valid = _validate_dump_for_status(path)
            if valid is None:
                # 工具暂时失败: 不下结论不缓存, 按「存在但未验证」呈现, 下次重试。
                return _backup_entry(path, stat)
            _lightweight_backup_validation[cache_key] = valid
        if valid:
            return _backup_entry(path, stat)
    return None
