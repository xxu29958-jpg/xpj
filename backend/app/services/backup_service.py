"""Database backup helpers for the Owner Console.

Backups live under the writable data dir at ``DATA_ROOT/backups`` (``backend/
backups/`` in a source run; ``ticketbox-data/backups/`` next to a frozen EXE).
The same location is used by ``scripts/maintenance_ticketbox.ps1 -Backup`` so a
backup created from the Owner Console is interchangeable with one created by
the scheduled task.

The backup mechanism is dialect-dispatched (ADR-0041 phase-2): SQLite uses the
Online Backup API into a ``.db`` snapshot; PostgreSQL shells out to ``pg_dump
-Fc`` into a ``.dump`` custom-format archive. The active dialect is decided by
``DATABASE_URL`` so a given deployment only ever produces and lists one format.
Restoring remains an explicit local command (``scripts/restore_ticketbox_db.ps1``
for SQLite; ``pg_restore`` per the Postgres runbook).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import DATA_ROOT, get_settings
from app.errors import AppError
from app.services.postgres_backup_validation_service import is_postgres_backup_valid
from app.services.sqlite_backup_validation_service import is_sqlite_backup_valid
from app.services.time_service import now_utc

# Backups live under the writable data dir (DATA_ROOT/backups). In a frozen EXE
# the program root is PyInstaller's throwaway _MEIPASS dir, so deriving the
# backup folder from __file__ would write snapshots that vanish on restart.
_BACKUP_DIR = DATA_ROOT / "backups"
_PREFIX = "ticketbox-"
_SQLITE_SUFFIX = ".db"
_POSTGRES_SUFFIX = ".dump"

_logger = logging.getLogger(__name__)


def _is_postgres() -> bool:
    return get_settings().database_url.startswith("postgresql")


def _backup_suffix() -> str:
    """File suffix for the active dialect's backups (``.db`` / ``.dump``)."""
    return _POSTGRES_SUFFIX if _is_postgres() else _SQLITE_SUFFIX


@dataclass(frozen=True)
class BackupEntry:
    file_name: str
    size_bytes: int
    created_at: datetime
    kind: str  # "scheduled" / "manual" / "pre-restore" / "pre-v0.3" / "pre-v1.0"


def _backup_dir() -> Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return _BACKUP_DIR


def backup_directory_label() -> str:
    """备份目录的**相对**展示标签(如 ``backend\\backups`` / ``ticketbox-data\\backups``)。

    只取数据根末段 + ``backups``,**不暴露主机绝对路径**(测试 no_uploads_path_leak
    禁止页面出现 ``C:\\`` / ``E:\\``)。源码部署 = backend、冻结 EXE = ticketbox-data;
    与维护/恢复脚本(已跟随 ``TICKETBOX_DATA_DIR``)写/读的位置一致。
    """
    return f"{_BACKUP_DIR.parent.name}\\{_BACKUP_DIR.name}"


def _classify(name: str) -> str:
    if name.startswith("ticketbox-before-restore-"):
        return "pre-restore"
    if name.startswith("ticketbox-pre-v1.0-"):
        return "pre-v1.0"
    if name.startswith("ticketbox-pre-v0.3"):
        return "pre-v0.3"
    if name.startswith("ticketbox-manual-"):
        return "manual"
    return "scheduled"


def list_backups() -> list[BackupEntry]:
    """Return existing backups for the active dialect, newest first."""
    directory = _backup_dir()
    is_valid = is_postgres_backup_valid if _is_postgres() else _sqlite_integrity_ok
    entries: list[BackupEntry] = []
    for path in directory.glob(f"{_PREFIX}*{_backup_suffix()}"):
        if not path.is_file():
            continue
        if not is_valid(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        created_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
        entries.append(
            BackupEntry(
                file_name=path.name,
                size_bytes=int(stat.st_size),
                created_at=created_at,
                kind=_classify(path.name),
            )
        )
    entries.sort(key=lambda item: item.created_at, reverse=True)
    return entries


def latest_backup() -> BackupEntry | None:
    items = list_backups()
    return items[0] if items else None


def is_backup_valid(file_name: str) -> bool:
    """Return True only for an existing, well-formed backup file of the active dialect."""
    if Path(file_name).name != file_name:
        return False
    if not file_name.startswith(_PREFIX) or not file_name.endswith(_backup_suffix()):
        return False
    path = _backup_dir() / file_name
    return is_postgres_backup_valid(path) if _is_postgres() else _sqlite_integrity_ok(path)


def create_manual_backup() -> BackupEntry:
    """Snapshot the live database into ``backups/`` (dialect-dispatched).

    SQLite uses the Online Backup API (consistent even under WAL / concurrent
    writes — ``shutil.copy2`` is intentionally NOT used); PostgreSQL shells out
    to ``pg_dump -Fc``. Raises :class:`AppError` on an unsupported URL, a missing
    file, or a failed dump.
    """
    return _create_backup(prefix="ticketbox-manual", kind="manual")


def create_pre_v1_backup() -> BackupEntry:
    """Create a named pre-v1.0 backup for migration rehearsals (dialect-dispatched)."""
    return _create_backup(prefix="ticketbox-pre-v1.0", kind="pre-v1.0")


def _create_backup(*, prefix: str, kind: str) -> BackupEntry:
    if _is_postgres():
        return _create_postgres_backup(prefix=prefix, kind=kind)
    return _create_sqlite_backup(prefix=prefix, kind=kind)


def _create_sqlite_backup(*, prefix: str, kind: str) -> BackupEntry:
    cfg = get_settings()
    if not cfg.database_url.startswith("sqlite:///"):
        raise AppError(
            "invalid_request",
            "仅支持 SQLite 数据库的备份，当前数据库不是 SQLite。",
            status_code=400,
        )

    db_path = Path(cfg.database_url[len("sqlite:///") :])
    if not db_path.is_file():
        raise AppError(
            "invalid_request",
            "未找到数据库文件，无法备份。请先确认后端已正常初始化。",
            status_code=400,
        )

    directory = _backup_dir()
    stamp = now_utc().astimezone().strftime("%Y%m%d-%H%M%S")
    target = directory / f"{prefix}-{stamp}-{uuid4().hex[:8]}.db"

    temp_target = directory / f".{target.name}.tmp-{uuid4().hex}"
    try:
        # SQLite Online Backup API — safe under WAL / concurrent writes.
        src_conn = sqlite3.connect(str(db_path))
        try:
            dst_conn = sqlite3.connect(str(temp_target))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        if not _sqlite_integrity_ok(temp_target):
            raise AppError(
                "invalid_request",
                "数据库备份校验失败，未写入最终备份文件。",
                status_code=500,
            )
        temp_target.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_target.unlink()

    stat = target.stat()
    created_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
    return BackupEntry(
        file_name=target.name,
        size_bytes=int(stat.st_size),
        created_at=created_at,
        kind=kind,
    )


def _create_postgres_backup(*, prefix: str, kind: str) -> BackupEntry:
    libpq_url = _libpq_url(get_settings().database_url)
    directory = _backup_dir()
    stamp = now_utc().astimezone().strftime("%Y%m%d-%H%M%S")
    target = directory / f"{prefix}-{stamp}-{uuid4().hex[:8]}{_POSTGRES_SUFFIX}"
    temp_target = directory / f".{target.name}.tmp-{uuid4().hex}"
    try:
        result = subprocess.run(  # noqa: S603 (binary resolved from PATH/override, fixed args)
            [_pg_dump_binary(), "--format=custom", "--file", str(temp_target), "--dbname", libpq_url],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            # pg_dump stderr can echo the DSN/host — log it, never surface it (§10).
            _logger.warning("pg_dump failed (rc=%s): %s", result.returncode, result.stderr.strip())
            raise AppError("server_error", "数据库备份失败，请查看后端日志。", status_code=500)
        if not is_postgres_backup_valid(temp_target):
            raise AppError(
                "server_error", "数据库备份校验失败，未写入最终备份文件。", status_code=500
            )
        temp_target.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_target.unlink()

    stat = target.stat()
    created_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
    return BackupEntry(
        file_name=target.name,
        size_bytes=int(stat.st_size),
        created_at=created_at,
        kind=kind,
    )


def _libpq_url(database_url: str) -> str:
    """SQLAlchemy URL -> libpq URL: drop the ``+driver`` tag pg_dump rejects."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", database_url, count=1)


def _pg_dump_binary() -> str:
    binary = os.getenv("PG_DUMP_PATH") or shutil.which("pg_dump")
    if not binary:
        raise AppError(
            "server_error", "未找到 pg_dump，无法备份 PostgreSQL 数据库。", status_code=500
        )
    return binary


def _sqlite_integrity_ok(path: Path) -> bool:
    return is_sqlite_backup_valid(path)
