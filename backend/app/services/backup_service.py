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
import ipaddress
import logging
import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.config import DATA_ROOT, get_settings
from app.errors import AppError
from app.services.postgres_backup_validation_service import find_pg_binary, is_postgres_backup_valid
from app.services.secure_file import (
    hold_protected_file_for_read,
    write_protected_file_exclusive,
)
from app.services.time_service import now_utc

# Backups live under the writable data dir (DATA_ROOT/backups). In a frozen EXE
# the program root is PyInstaller's throwaway _MEIPASS dir, so deriving the
# backup folder from __file__ would write snapshots that vanish on restart.
_BACKUP_DIR = DATA_ROOT / "backups"
_PREFIX = "ticketbox-"
_SUFFIX = ".dump"
_PG_DUMP_TIMEOUT_SECONDS = 5 * 60
_PG_DUMP_LOCK_WAIT_MILLISECONDS = 30_000
_PG_TOOL_QUERY_KEYS = frozenset(
    {"connect_timeout", "hostaddr", "options", "require_auth", "sslmode"}
)
_PG_TOOL_SSL_MODES = frozenset(
    {"allow", "disable", "prefer", "require", "verify-ca", "verify-full"}
)
_DATABASE_URL_ENVIRONMENT = frozenset(
    {
        "DATABASE_URL",
        "DRILL_RESTORE_URL",
        "DRILL_SOURCE_URL",
        "SMOKE_DATABASE_URL",
        "XPJ_TEST_ADMIN_URL",
        "XPJ_TEST_DATABASE_URL",
    }
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupEntry:
    file_name: str
    size_bytes: int
    created_at: datetime
    kind: str  # "scheduled" / "manual" / "pre-restore" / "pre-v0.3" / "pre-upgrade"


@dataclass(frozen=True)
class _PgToolConnection:
    database_url: str
    username: str
    host: str
    port: int
    database: str
    password: str | None


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


# 进程内缓存: (file_name, mtime_ns, size) -> ``pg_restore --list`` 验证结果
# (PR #253 R2 bot-P1)。只原地增删 (dict[key]=value / clear), 不整体重绑。
_lightweight_backup_validation: dict[tuple[str, int, int], bool] = {}

def latest_backup_lightweight() -> BackupEntry | None:
    """Newest VALID dump — a corrupt newest one yields to older valid ones.

    Same "newest valid" semantics as ``latest_backup()`` (PR #253 R3), but
    validates candidates newest-first via ``pg_restore --list``, memoized per
    ``(name, mtime_ns, size)``: steady state spawns no subprocess and each file
    is validated at most once per process. Restore/health flows keep the
    every-dump fully validated caliber.
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
            valid = _lightweight_backup_validation[cache_key] = is_postgres_backup_valid(path)
        if valid:
            return BackupEntry(
                file_name=path.name,
                size_bytes=int(stat.st_size),
                created_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
                kind=_classify(path.name),
            )
    return None


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
    connection = _pg_tool_connection(get_settings().database_url)
    directory = _backup_dir()
    stamp = now_utc().astimezone().strftime("%Y%m%d-%H%M%S")
    target = directory / f"{prefix}-{stamp}-{uuid4().hex[:8]}{_SUFFIX}"
    temp_target = directory / f".{target.name}.tmp-{uuid4().hex}"
    try:
        try:
            with _pg_tool_environment(connection) as environment:
                result = subprocess.run(  # noqa: S603 (resolved binary, fixed args)
                    [
                        _pg_dump_binary(),
                        "--no-password",
                        f"--lock-wait-timeout={_PG_DUMP_LOCK_WAIT_MILLISECONDS}",
                        "--format=custom",
                        "--file",
                        str(temp_target),
                        "--dbname",
                        connection.database_url,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    timeout=_PG_DUMP_TIMEOUT_SECONDS,
                )
        except (OSError, subprocess.TimeoutExpired):
            _logger.warning("pg_dump could not complete; diagnostic output omitted")
            raise AppError(
                "server_error", "数据库备份未在安全时限内完成。", status_code=500
            ) from None
        if result.returncode != 0:
            # Native diagnostics may repeat connection material. Keep them out of
            # logs entirely; the return code is enough for the operator-facing gate.
            _logger.warning("pg_dump failed (rc=%s); diagnostic output omitted", result.returncode)
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


def _pg_tool_connection(database_url: str) -> _PgToolConnection:
    """Split a SQLAlchemy URL into passwordless libpq URL + child-only password."""
    try:
        parsed = make_url(database_url)
        backend_name = parsed.get_backend_name()
    except (ArgumentError, TypeError, ValueError):
        raise AppError("server_error", "数据库备份配置无效。", status_code=500) from None
    if backend_name != "postgresql":
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)

    password = parsed.password
    query: dict[str, str] = {}
    for raw_key, raw_value in parsed.query.items():
        key = raw_key.casefold()
        if (
            key in query
            or key not in _PG_TOOL_QUERY_KEYS
            or not isinstance(raw_value, str)
            or any(character in raw_value for character in "\x00\r\n")
        ):
            raise AppError("server_error", "数据库备份配置无效。", status_code=500)
        query[key] = raw_value
    if query.get("require_auth") != "scram-sha-256":
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)
    if not parsed.username or not parsed.host or not parsed.database:
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)
    query.setdefault("connect_timeout", "5")
    query.setdefault("sslmode", "prefer")
    try:
        if not 1 <= int(query["connect_timeout"]) <= 30:
            raise ValueError
        if "hostaddr" in query:
            host_address = ipaddress.ip_address(query["hostaddr"])
            host = parsed.host.casefold()
            if host == "localhost":
                if host_address not in {
                    ipaddress.ip_address("127.0.0.1"),
                    ipaddress.ip_address("::1"),
                }:
                    raise ValueError
            elif host_address != ipaddress.ip_address(host):
                raise ValueError
    except ValueError:
        raise AppError("server_error", "数据库备份配置无效。", status_code=500) from None
    if query.get("sslmode", "prefer") not in _PG_TOOL_SSL_MODES:
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)

    try:
        passwordless = URL.create(
            drivername="postgresql",
            username=parsed.username,
            host=parsed.host,
            port=parsed.port or 5432,
            database=parsed.database,
            query=query,
        )
        rendered_url = passwordless.render_as_string(hide_password=False)
    except (TypeError, ValueError):
        raise AppError("server_error", "数据库备份配置无效。", status_code=500) from None
    return _PgToolConnection(
        database_url=rendered_url,
        username=parsed.username,
        host=parsed.host,
        port=parsed.port or 5432,
        database=parsed.database,
        password=password,
    )


def _escape_pgpass(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


@contextlib.contextmanager
def _validated_inherited_passfile() -> Iterator[Path]:
    raw = os.environ.get("PGPASSFILE")
    if not raw:
        raise AppError("server_error", "数据库备份凭据不可用。", status_code=500)
    try:
        protected_file = hold_protected_file_for_read(Path(raw))
        resolved = protected_file.__enter__()
    except (OSError, ValueError):
        raise AppError("server_error", "数据库备份凭据不可用。", status_code=500) from None
    try:
        yield resolved
    finally:
        protected_file.__exit__(None, None, None)


@contextlib.contextmanager
def _pg_tool_environment(connection: _PgToolConnection) -> Iterator[dict[str, str]]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PG")
        and key.upper() not in _DATABASE_URL_ENVIRONMENT
    }
    if connection.password is None:
        with _validated_inherited_passfile() as passfile:
            environment["PGPASSFILE"] = str(passfile)
            yield environment
        return

    passfile = _backup_dir() / f".pgpass-{os.getpid()}-{uuid4().hex}"
    line = ":".join(
        _escape_pgpass(value)
        for value in (
            connection.host,
            str(connection.port),
            connection.database,
            connection.username,
            connection.password,
        )
    )
    published = False
    try:
        write_protected_file_exclusive(passfile, f"{line}\n")
        published = True
        with hold_protected_file_for_read(passfile) as protected_passfile:
            environment["PGPASSFILE"] = str(protected_passfile)
            yield environment
    finally:
        if published or passfile.exists():
            passfile.unlink(missing_ok=True)


def _pg_dump_binary() -> str:
    binary = find_pg_binary("pg_dump", "PG_DUMP_PATH")
    if not binary:
        raise AppError(
            "server_error", "未找到 pg_dump，无法备份 PostgreSQL 数据库。", status_code=500
        )
    return binary
