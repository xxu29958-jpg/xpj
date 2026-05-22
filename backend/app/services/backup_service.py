"""Database backup helpers for the Owner Console.

Backups live next to the SQLite database under ``backend/backups/``. The same
location is used by ``scripts/maintenance_ticketbox.ps1 -Backup`` so that a
backup created from the Owner Console is interchangeable with one created by
the scheduled task.

This service intentionally only handles SQLite Online Backup snapshots.
Restoring is done by ``scripts/restore_ticketbox_db.ps1`` and remains an
explicit local command.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.errors import AppError
from app.services.sqlite_backup_validation_service import is_sqlite_backup_valid
from app.services.time_service import now_utc

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BACKUP_DIR = _BACKEND_ROOT / "backups"
_PREFIX = "ticketbox-"
_SUFFIX = ".db"


@dataclass(frozen=True)
class BackupEntry:
    file_name: str
    size_bytes: int
    created_at: datetime
    kind: str  # "scheduled" / "manual" / "pre-restore" / "pre-v0.3" / "pre-v1.0"


def _backup_dir() -> Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return _BACKUP_DIR


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
    """Return existing backups, newest first."""
    directory = _backup_dir()
    entries: list[BackupEntry] = []
    for path in directory.glob(f"{_PREFIX}*{_SUFFIX}"):
        if not path.is_file():
            continue
        if not _sqlite_integrity_ok(path):
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
    """Return True only for an existing, well-formed backup file."""
    if Path(file_name).name != file_name:
        return False
    if not file_name.startswith(_PREFIX) or not file_name.endswith(_SUFFIX):
        return False
    return _sqlite_integrity_ok(_backup_dir() / file_name)


def create_manual_backup() -> BackupEntry:
    """Snapshot the live SQLite database into ``backups/`` using the SQLite
    Online Backup API.

    ``shutil.copy2`` is intentionally NOT used: SQLite may be in WAL mode or
    mid-write. ``sqlite3.Connection.backup()`` guarantees a consistent snapshot
    even under concurrent writes.

    Raises :class:`AppError` if the database URL is not SQLite or the file is
    missing.
    """
    return _create_sqlite_backup(prefix="ticketbox-manual", kind="manual")


def create_pre_v1_backup() -> BackupEntry:
    """Create a named pre-v1.0 backup for migration rehearsals."""

    return _create_sqlite_backup(prefix="ticketbox-pre-v1.0", kind="pre-v1.0")


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


def _sqlite_integrity_ok(path: Path) -> bool:
    return is_sqlite_backup_valid(path)
