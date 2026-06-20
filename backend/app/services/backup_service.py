"""Database backup helpers for the Owner Console.

Backups live under the writable data dir at ``DATA_ROOT/backups`` (``backend/
backups/`` in a source run; ``ticketbox-data/backups/`` next to a frozen EXE).
The same location is used by ``scripts/maintenance_ticketbox.ps1 -Backup`` so a
backup created from the Owner Console is interchangeable with one created by
the scheduled task.

The backend is PostgreSQL-only (ADR-0041): backups shell out to ``pg_dump -Fc``
into a ``.dump`` custom-format archive. Restoring remains an explicit local
command (``pg_restore`` per the Postgres runbook).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import DATA_ROOT, get_settings
from app.errors import AppError
from app.services.postgres_backup_validation_service import find_pg_binary, is_postgres_backup_valid
from app.services.time_service import now_utc

# Backups live under the writable data dir (DATA_ROOT/backups). In a frozen EXE
# the program root is PyInstaller's throwaway _MEIPASS dir, so deriving the
# backup folder from __file__ would write snapshots that vanish on restart.
_BACKUP_DIR = DATA_ROOT / "backups"
_PREFIX = "ticketbox-"
_SUFFIX = ".dump"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupEntry:
    file_name: str
    size_bytes: int
    created_at: datetime
    kind: str  # "scheduled" / "manual" / "pre-restore" / "pre-v0.3" / "pre-upgrade"


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
    if name.startswith("ticketbox-pre-upgrade-"):
        return "pre-upgrade"
    if name.startswith("ticketbox-pre-v0.3"):
        return "pre-v0.3"
    if name.startswith("ticketbox-manual-"):
        return "manual"
    return "scheduled"


def list_backups() -> list[BackupEntry]:
    """Return existing pg_dump backups, newest first."""
    directory = _backup_dir()
    entries: list[BackupEntry] = []
    for path in directory.glob(f"{_PREFIX}*{_SUFFIX}"):
        if not path.is_file():
            continue
        if not is_postgres_backup_valid(path):
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


@dataclass(frozen=True)
class BackupHealth:
    """Dashboard view of the newest valid backup's freshness."""

    latest: BackupEntry | None
    age_hours: int | None  # None when no valid backup exists at all
    stale: bool


def backup_health(*, stale_after_hours: int = 48) -> BackupHealth:
    """Health of the backup chain for the Owner Console dashboard.

    ``stale`` means no valid backup newer than ``stale_after_hours`` (the
    nightly TicketboxBackup task has likely been failing — a 6-day silent
    chain break in 2026-06 motivated surfacing this). The threshold lives
    here, not in the route/template (§1: business judgement is service-side).
    """
    entry = latest_backup()
    if entry is None:
        return BackupHealth(latest=None, age_hours=None, stale=True)
    age_hours = int((now_utc().astimezone() - entry.created_at).total_seconds() // 3600)
    return BackupHealth(latest=entry, age_hours=age_hours, stale=age_hours >= stale_after_hours)


def is_backup_valid(file_name: str) -> bool:
    """Return True only for an existing, well-formed pg_dump backup file."""
    if Path(file_name).name != file_name:
        return False
    if not file_name.startswith(_PREFIX) or not file_name.endswith(_SUFFIX):
        return False
    path = _backup_dir() / file_name
    return is_postgres_backup_valid(path)


def create_manual_backup() -> BackupEntry:
    """Snapshot the live database into ``backups/`` via ``pg_dump -Fc``.

    Takes the backup concurrency lock (BUG-2): if a scheduled task or another
    manual backup is already running, raises ``backup_in_progress`` (409) and the
    operator simply retries. Raises :class:`AppError` on a missing ``pg_dump``
    binary or a failed dump.
    """
    with _backup_lock():
        return _run_pg_dump(prefix="ticketbox-manual", kind="manual")


def create_pre_upgrade_backup() -> BackupEntry:
    """Snapshot the live database BEFORE an Alembic migration runs (model-invariant
    hardening P1). Same ``pg_dump -Fc`` as a manual backup but tagged ``pre-upgrade``
    so the pre-migration restore point is identifiable. Raises :class:`AppError` on a
    missing ``pg_dump`` binary or a failed dump (the startup gate turns that into a
    fail-closed abort — see ``app.database._backup_before_upgrade``).

    Deliberately does NOT take the backup concurrency lock: this is a pure dump
    (no rotation, so it cannot cause the BUG-2 rotation race) that runs
    single-threaded during startup and must be fail-closed. Taking the lock would
    let a leftover sentinel from a crashed run stall a legitimate migration — a
    startup-brick class we refuse to introduce. A concurrent scheduled dump is
    harmless: both produce independent archives and only the scheduled job rotates.
    """
    return _run_pg_dump(prefix="ticketbox-pre-upgrade", kind="pre-upgrade")


# ── Concurrency guard (BUG-2) ────────────────────────────────────────────────
# The Owner Console (``create_manual_backup``) and the scheduled Windows task
# (``backend/scripts/backup_database.ps1``) both write into the same ``backups/``
# directory. When two backup jobs overlap, their rotation/prune steps race on the
# dump files and the loser errors out (benign — no data loss, but the task result
# goes red). A shared sentinel lock file serializes backup *jobs* across both the
# Python and PowerShell entry points; the PowerShell side honours the same file
# name and TTL (see ``backup_database.ps1``). The startup pre-migration snapshot
# is deliberately unlocked (see ``create_pre_upgrade_backup``).
_LOCK_NAME = ".backup.lock"
# A pg_dump of a personal-finance database finishes in seconds; a lock older than
# this can only be a crashed job, so it is reclaimed rather than blocking forever.
_LOCK_STALE_SECONDS = 30 * 60


def _lock_path() -> Path:
    # Lives in backups/ but starts with '.', so it never matches the
    # ``ticketbox-*.dump`` glob used by list_backups / rotation / offsite sync.
    return _backup_dir() / _LOCK_NAME


def _lock_is_stale(path: Path) -> bool:
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False  # already gone — the next exclusive create will win
    return age_seconds > _LOCK_STALE_SECONDS


@contextlib.contextmanager
def _backup_lock() -> Iterator[None]:
    """Serialize backup jobs via an exclusive sentinel file (non-blocking).

    If another live job holds the lock, raise ``backup_in_progress`` (409) — the
    manual-backup operator simply retries. A lock older than
    ``_LOCK_STALE_SECONDS`` is treated as a crashed job and reclaimed; the
    ``O_EXCL`` create on the next loop arbitrates the reclaim race.
    """
    path = _lock_path()
    payload = f"{os.getpid()}\n{now_utc().isoformat()}\n".encode()
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lock_is_stale(path):
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(str(path))
                continue
            raise AppError("backup_in_progress", status_code=409) from None
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(str(path))


def _run_pg_dump(*, prefix: str, kind: str) -> BackupEntry:
    libpq_url = _libpq_url(get_settings().database_url)
    directory = _backup_dir()
    stamp = now_utc().astimezone().strftime("%Y%m%d-%H%M%S")
    target = directory / f"{prefix}-{stamp}-{uuid4().hex[:8]}{_SUFFIX}"
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
    binary = find_pg_binary("pg_dump", "PG_DUMP_PATH")
    if not binary:
        raise AppError(
            "server_error", "未找到 pg_dump，无法备份 PostgreSQL 数据库。", status_code=500
        )
    return binary
