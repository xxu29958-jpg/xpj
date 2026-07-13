"""Frozen-EXE entry point for the Ticketbox backend.

PyInstaller bundles the read-only program (the ``app`` package, static assets,
Jinja templates, ``alembic.ini`` and ``migrations/``). Everything the running
backend *writes* — uploaded images, ``.env`` overrides, logs, and PostgreSQL
backups — lives in a separate, writable ``ticketbox-data/`` folder next to the
EXE. The database itself runs in a local PostgreSQL service (see
docs/runbook/POSTGRES_MIGRATION.md), not in this folder. We point the app's
config there via env vars BEFORE importing ``app.*``, because :mod:`app.config`
resolves paths relative to its own location, which in a frozen build is the
throwaway extraction dir (``sys._MEIPASS``).

Run (frozen):   through the installer-validated Windows service contract
Run (dev):      python packaging/launch.py            (cwd = backend/)

The frozen build is windowed (``console=False``, ADR-0047 §8), so a running
service has no stdout/stderr. ``main()`` configures logging to a rotating file
under ``<data>/logs/`` BEFORE importing the app and tells uvicorn not to re-point
its handlers at ``sys.stdout`` — see :func:`_build_log_config`.
"""

from __future__ import annotations

import json
import ntpath
import os
import re
import stat
import sys
from datetime import UTC, datetime
from json import dumps
from pathlib import Path

_VOLUME_IDENTITY_PATTERN = re.compile(
    r"^\\\\\?\\Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}\\$",
    re.IGNORECASE,
)
_VOLUME_IDENTITY_PREFIX_PATTERN = re.compile(
    r"^(\\\\\?\\Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}\\)",
    re.IGNORECASE,
)
_FROZEN_HOST_AUTHORITY_KEYS = (
    "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH",
    "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH",
    "TICKETBOX_DATA_ROOT_MARKER_PATH",
    "TICKETBOX_DATA_VOLUME_IDENTITY",
    "TICKETBOX_OWNER_RECOVERY_CHANNEL",
)
_OWNER_RECOVERY_CHANNELS = frozenset({"development", "managed_host", "operator"})
_BOOTSTRAP_RECOVERY_GUARD_NAME = "bootstrap-exposure-recovery-pending"


def _bundle_dir() -> Path:
    """Directory the EXE was launched from (read-only program root when frozen).

    Frozen: the folder the user dropped the EXE in (``sys.executable``). Used
    ONLY to locate the *default* writable folder — never to write into when an
    installer/service has pre-set ``TICKETBOX_DATA_DIR`` (the EXE may sit in a
    read-only ``Program Files``). Dev: the backend/ project root (two levels up).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _resolve_writable_data_dir() -> Path:
    """Writable data root for files the backend *creates* (uploads, .env, backups).

    Honors an installer/service-preset ``TICKETBOX_DATA_DIR`` — the ADR-0047
    service deployment points it at the machine ``CommonApplicationData/Ticketbox/app`` root because the
    onedir EXE lives in a read-only/locked location. Only when it is unset/blank
    do we fall back to a ``ticketbox-data/`` folder next to the EXE (dev / the
    single-folder 档 A install). Resolving a preset HERE — instead of computing
    the EXE-adjacent default and unconditionally overwriting the preset later —
    is what lets the service run from a read-only ``Program Files`` install.
    """
    preset = os.environ.get("TICKETBOX_DATA_DIR", "").strip()
    if preset:
        return Path(os.path.abspath(preset))
    return _bundle_dir() / "ticketbox-data"


def _windows_final_volume_path(path: Path) -> str:
    if os.name != "nt":
        raise RuntimeError("runtime DataRoot volume authority is Windows-only")

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(path),
        0x80,  # FILE_READ_ATTRIBUTES
        0x1 | 0x2 | 0x4,  # FILE_SHARE_READ | WRITE | DELETE
        None,
        3,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), f"cannot open runtime DataRoot binding: {path}")
    try:
        size = 1024
        while True:
            buffer = ctypes.create_unicode_buffer(size)
            written = get_final_path(handle, buffer, size, 0x1)  # VOLUME_NAME_GUID
            if written == 0:
                raise OSError(
                    ctypes.get_last_error(),
                    f"cannot resolve runtime DataRoot volume: {path}",
                )
            if written < size:
                final_path = buffer.value
                break
            size = written + 1
    finally:
        close_handle(handle)

    match = _VOLUME_IDENTITY_PREFIX_PATTERN.match(final_path)
    if match is None or _VOLUME_IDENTITY_PATTERN.fullmatch(match.group(1)) is None:
        raise RuntimeError("runtime DataRoot binding did not resolve to a Volume GUID path")
    return match.group(1).upper() + final_path[len(match.group(1)) :]


def _windows_final_volume_identity(path: Path) -> str:
    final_path = _windows_final_volume_path(path)
    match = _VOLUME_IDENTITY_PREFIX_PATTERN.match(final_path)
    if match is None:
        raise RuntimeError("runtime DataRoot binding did not resolve to a Volume GUID path")
    return match.group(0).upper()


def _is_reparse_entry(entry: os.stat_result) -> bool:
    attributes = getattr(entry, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(entry.st_mode) or bool(attributes & reparse_attribute)


def _assert_runtime_marker_no_follow(marker_path: Path) -> None:
    try:
        marker_entry = marker_path.lstat()
    except OSError as exc:
        raise RuntimeError("runtime DataRoot marker is unavailable") from exc
    if _is_reparse_entry(marker_entry) or not stat.S_ISREG(marker_entry.st_mode):
        raise RuntimeError("runtime DataRoot marker must be a regular non-reparse file")

    runtime_root = marker_path.parent
    try:
        runtime_root_entry = runtime_root.lstat()
    except OSError as exc:
        raise RuntimeError("runtime DataRoot junction is unavailable") from exc
    if not _is_reparse_entry(runtime_root_entry):
        raise RuntimeError("runtime DataRoot marker parent must be the runtime junction")

    cursor = runtime_root.parent
    while True:
        try:
            entry = cursor.lstat()
        except OSError as exc:
            raise RuntimeError("runtime DataRoot binding ancestor is unavailable") from exc
        if _is_reparse_entry(entry) or not stat.S_ISDIR(entry.st_mode):
            raise RuntimeError("runtime DataRoot binding ancestor is not a regular directory")
        parent = cursor.parent
        if parent == cursor:
            return
        cursor = parent


def _canonical_marker_windows_path(raw: str, *, label: str) -> Path:
    if not raw or not Path(raw).is_absolute():
        raise RuntimeError(f"runtime DataRoot marker {label} is not an absolute path")
    canonical = Path(os.path.abspath(raw))
    drive, tail = ntpath.splitdrive(str(canonical))
    if re.fullmatch(r"[A-Za-z]:", drive) is None or not tail.startswith("\\"):
        raise RuntimeError(f"runtime DataRoot marker {label} is not a local drive path")
    if ntpath.normcase(ntpath.normpath(raw)) != ntpath.normcase(str(canonical)):
        raise RuntimeError(f"runtime DataRoot marker {label} is not canonical")
    return canonical


def _volume_bound_marker_path(data_root: Path, volume_identity: str) -> str:
    _drive, tail = ntpath.splitdrive(str(data_root))
    relative = tail.lstrip("\\")
    if not relative:
        raise RuntimeError("runtime DataRoot marker cannot bind a volume root")
    return volume_identity + relative


def _expected_frozen_install_dir() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("runtime DataRoot authority requires the frozen backend")
    executable = Path(os.path.abspath(sys.executable))
    if len(executable.parents) < 3:
        raise RuntimeError("frozen backend path does not match the installer layout")
    return executable.parents[2]


def _assert_frozen_host_authority(host_authority: dict[str, str | None]) -> None:
    if not getattr(sys, "frozen", False):
        return
    missing = [
        key
        for key in _FROZEN_HOST_AUTHORITY_KEYS
        if not (host_authority.get(key) or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "frozen backend host authority is incomplete: " + ", ".join(missing)
        )
    owner_recovery_channel = host_authority["TICKETBOX_OWNER_RECOVERY_CHANNEL"]
    if owner_recovery_channel not in _OWNER_RECOVERY_CHANNELS:
        raise RuntimeError("frozen backend owner recovery capability is invalid")


def _assert_bootstrap_guard_runtime_binding(marker_path: Path) -> None:
    bootstrap_guard_value = os.environ.get(
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH", ""
    ).strip()
    if not bootstrap_guard_value:
        return
    bootstrap_guard_path = Path(os.path.abspath(bootstrap_guard_value))
    expected_bootstrap_guard = marker_path.parent / _BOOTSTRAP_RECOVERY_GUARD_NAME
    if os.path.normcase(str(bootstrap_guard_path)) != os.path.normcase(
        str(expected_bootstrap_guard)
    ):
        raise RuntimeError(
            "bootstrap recovery guard is not bound to the runtime DataRoot projection"
        )


def _assert_runtime_data_root_authority(data_dir: Path) -> Path | None:
    marker_value = os.environ.get("TICKETBOX_DATA_ROOT_MARKER_PATH", "").strip()
    volume_value = os.environ.get("TICKETBOX_DATA_VOLUME_IDENTITY", "").strip()
    if not marker_value and not volume_value:
        return None
    if not marker_value or not volume_value:
        raise RuntimeError("runtime DataRoot authority is incomplete")
    if _VOLUME_IDENTITY_PATTERN.fullmatch(volume_value) is None:
        raise RuntimeError("runtime DataRoot Volume GUID is malformed")

    marker_path = Path(os.path.abspath(marker_value))
    expected_data_dir = marker_path.parent / "app"
    if os.path.normcase(str(data_dir)) != os.path.normcase(str(expected_data_dir)):
        raise RuntimeError("runtime DataRoot marker does not bind the configured app directory")
    _assert_bootstrap_guard_runtime_binding(marker_path)
    _assert_runtime_marker_no_follow(marker_path)
    try:
        marker_bytes = marker_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("runtime DataRoot marker is unavailable") from exc
    if not 0 < len(marker_bytes) <= 16384:
        raise RuntimeError("runtime DataRoot marker size is invalid")
    try:
        marker_text = marker_bytes.decode("utf-8", errors="strict")
        marker = json.loads(marker_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("runtime DataRoot marker is malformed") from exc
    if not isinstance(marker, dict) or set(marker) != {
        "schema",
        "data_root",
        "install_dir",
        "data_volume_identity",
    }:
        raise RuntimeError("runtime DataRoot marker has an unsupported shape")
    if marker.get("schema") != "ticketbox-data-root-v2" or not isinstance(
        marker.get("data_root"), str
    ) or not isinstance(marker.get("install_dir"), str):
        raise RuntimeError("runtime DataRoot marker has an unsupported binding")
    expected_volume = volume_value.upper()
    if str(marker.get("data_volume_identity", "")).upper() != expected_volume:
        raise RuntimeError("runtime DataRoot marker Volume GUID does not match SCM authority")
    marker_data_root = _canonical_marker_windows_path(
        marker["data_root"],
        label="data_root",
    )
    marker_install_dir = _canonical_marker_windows_path(
        marker["install_dir"],
        label="install_dir",
    )
    final_runtime_root = _windows_final_volume_path(marker_path.parent)
    final_volume_match = _VOLUME_IDENTITY_PREFIX_PATTERN.match(final_runtime_root)
    if final_volume_match is None or final_volume_match.group(0).upper() != expected_volume:
        raise RuntimeError("runtime DataRoot junction resolved to another volume")
    expected_runtime_root = _volume_bound_marker_path(marker_data_root, expected_volume)
    if ntpath.normcase(final_runtime_root.rstrip("\\")) != ntpath.normcase(
        expected_runtime_root.rstrip("\\")
    ):
        raise RuntimeError("runtime DataRoot junction does not match the marker data_root")
    if os.path.normcase(str(marker_install_dir)) != os.path.normcase(
        str(_expected_frozen_install_dir())
    ):
        raise RuntimeError("runtime DataRoot marker does not match the frozen install directory")
    return marker_path.parent


def configure_environment() -> Path:
    """Point the app at a writable data dir; return that dir.

    Installed frozen builds require the complete host authority injected by the
    validated service contract. Source mode may omit that contract and resolve a
    local writable directory. A user-supplied ``<data>/.env`` then wins for the
    business/runtime values it sets (override=True), but never for host authority.
    ``DATABASE_URL`` is not defaulted here because PostgreSQL remains authoritative.
    """
    data_dir = _resolve_writable_data_dir()
    # These values are supplied by the host/service contract.  The writable
    # app .env may configure business/runtime settings, but it must never move
    # the process to another data root or suppress an installer-owned guard.
    host_authority = {
        key: os.environ.get(key)
        for key in _FROZEN_HOST_AUTHORITY_KEYS
    }
    _assert_frozen_host_authority(host_authority)
    _assert_runtime_data_root_authority(data_dir)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    # Anchor app.config.DATA_ROOT here so writable files the backend *creates*
    # (Owner Console settings .env, PostgreSQL backups) persist in this folder
    # rather than the frozen build's throwaway _MEIPASS extraction dir. We
    # normalize the (possibly preset) value before the .env load and before
    # main() imports app.* so app.config reads the same resolved path we just
    # mkdir'd. This assignment is now idempotent with a preset (data_dir == the
    # resolved preset), so it normalizes rather than clobbering a service path.
    os.environ["TICKETBOX_DATA_DIR"] = str(data_dir)

    env_file = data_dir / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, encoding="utf-8-sig", override=True)

    os.environ["TICKETBOX_DATA_DIR"] = str(data_dir)
    for key, value in host_authority.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    # DATABASE_URL is intentionally not defaulted: the backend is PostgreSQL-only.
    # A user .env may set it; otherwise app.config supplies the local-PostgreSQL
    # default (the EXE assumes a local PostgreSQL service is installed).
    os.environ.setdefault("UPLOAD_DIR", str(data_dir / "uploads"))
    return data_dir


def _maintenance_result_path(data_dir: Path) -> Path:
    return data_dir / "logs" / "bootstrap-exposure-recovery-result.json"


def _write_maintenance_result(
    data_dir: Path,
    *,
    operation_id: str,
    state: str,
    error_code: str = "",
    error_type: str = "",
) -> None:
    result_path = _maintenance_result_path(data_dir)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "ticketbox-maintenance-result-v1",
        "action": "rotate-exposed-bootstrap",
        "operation_id": operation_id,
        "state": state,
        "error_code": error_code,
        "error_type": error_type,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
    }
    temporary = result_path.with_name(f".{result_path.name}.{os.getpid()}.tmp")
    temporary.write_text(dumps(payload, ensure_ascii=True), encoding="utf-8")
    os.replace(temporary, result_path)


def _maintenance_error_code(exc: BaseException) -> str:
    from sqlalchemy.exc import SQLAlchemyError

    from app.errors import AppError
    from app.services.identity_service import ReplacementCredentialCollisionError

    if isinstance(exc, ReplacementCredentialCollisionError):
        return "replacement_credential_collision"
    if isinstance(exc, AppError):
        return f"application:{exc.error}"
    if isinstance(exc, SQLAlchemyError):
        return "database_error"
    if isinstance(exc, OSError):
        return "io_error"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "runtime_error"


def _run_maintenance_action(data_dir: Path) -> bool:
    action = os.environ.pop("TICKETBOX_MAINTENANCE_ACTION", "").strip()
    if not action:
        return False
    if action != "rotate-exposed-bootstrap":
        raise RuntimeError(f"unsupported Ticketbox maintenance action: {action}")
    exposed_secret = os.environ.pop("TICKETBOX_EXPOSED_BOOTSTRAP_SECRET", "")
    replacement_secret = os.environ.pop("TICKETBOX_REPLACEMENT_BOOTSTRAP_SECRET", "")
    operation_id = os.environ.pop("TICKETBOX_MAINTENANCE_OPERATION_ID", "").strip()
    if not exposed_secret or not replacement_secret:
        raise RuntimeError("bootstrap exposure recovery secrets are missing")
    if not operation_id:
        raise RuntimeError("bootstrap exposure recovery operation id is missing")

    from sqlalchemy.exc import SQLAlchemyError

    from app.database import SessionLocal
    from app.errors import AppError
    from app.services.identity_service import rotate_exposed_bootstrap_credentials

    _write_maintenance_result(data_dir, operation_id=operation_id, state="running")
    try:
        with SessionLocal() as db:
            rotate_exposed_bootstrap_credentials(
                db,
                exposed_secret=exposed_secret,
                replacement_secret=replacement_secret,
            )
    except (AppError, SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
        error_code = _maintenance_error_code(exc)
        _write_maintenance_result(
            data_dir,
            operation_id=operation_id,
            state="failed",
            error_code=error_code,
            error_type=type(exc).__name__,
        )
        import logging

        logging.getLogger(__name__).error(
            "Ticketbox maintenance failed: code=%s type=%s",
            error_code,
            type(exc).__name__,
        )
        raise
    _write_maintenance_result(data_dir, operation_id=operation_id, state="succeeded")
    return True


def _assert_bootstrap_recovery_not_pending(
    validated_runtime_junction: Path | None,
) -> None:
    """Refuse normal HTTP startup while an installer-owned rotation is pending."""
    configured = os.environ.get("TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH", "").strip()
    if not configured:
        return
    guard_path = Path(os.path.abspath(configured))
    pending = _host_guard_is_present_or_malformed(
        guard_path,
        allowed_reparse_ancestor=validated_runtime_junction,
    )
    if pending:
        raise RuntimeError(
            "bootstrap credential recovery is pending; run installer repair before starting HTTP"
        )


def _installer_runtime_recovery_guard_path() -> Path | None:
    configured = os.environ.get("TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH", "").strip()
    if not configured:
        return None
    return Path(os.path.abspath(configured))


def _host_guard_is_present_or_malformed(
    guard_path: Path,
    *,
    allowed_reparse_ancestor: Path | None = None,
) -> bool:
    """Inspect a host guard lexically so dangling reparse points fail closed.

    The bootstrap guard is intentionally projected through the one runtime
    DataRoot junction whose marker, volume and install binding were validated.
    No other reparse point is trusted, including the guard leaf itself.
    """
    normalized_allowed_reparse = (
        os.path.normcase(str(Path(os.path.abspath(allowed_reparse_ancestor))))
        if allowed_reparse_ancestor is not None
        else None
    )
    cursor = guard_path
    while True:
        try:
            entry = cursor.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            return True
        else:
            if _is_reparse_entry(entry):
                is_allowed_runtime_junction = (
                    normalized_allowed_reparse is not None
                    and cursor != guard_path
                    and os.path.normcase(str(Path(os.path.abspath(cursor))))
                    == normalized_allowed_reparse
                    and stat.S_ISDIR(entry.st_mode)
                )
                if not is_allowed_runtime_junction:
                    return True
            elif cursor == guard_path or not stat.S_ISDIR(entry.st_mode):
                return True
        parent = cursor.parent
        if parent == cursor:
            return False
        cursor = parent


def _installer_runtime_recovery_is_pending(guard_path: Path | None) -> bool:
    if guard_path is None:
        return False
    return _host_guard_is_present_or_malformed(guard_path)


class _InstallerRuntimeRecoveryGuard:
    _ALLOWED_PATHS = frozenset({"/api/health/installation", "/api/bootstrap/owner"})

    def __init__(self, app, guard_path: Path | None):
        self._app = app
        self._guard_path = guard_path

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        recovery_pending = _installer_runtime_recovery_is_pending(self._guard_path)
        if not recovery_pending:
            await self._app(scope, receive, send)
            return
        if scope.get("path") in self._ALLOWED_PATHS:
            projected_scope = dict(scope)
            projected_state = dict(scope.get("state") or {})
            projected_state["ticketbox_runtime_access_state"] = "repair_required"
            projected_scope["state"] = projected_state
            await self._app(projected_scope, receive, send)
            return

        body = json.dumps(
            {
                "error": "installer_recovery_pending",
                "message": "Installer repair must complete before normal traffic is accepted.",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _build_log_config(log_dir: Path, *, console: bool | None = None) -> dict:
    """Build a ``logging.config.dictConfig`` for the frozen backend.

    Everything — uvicorn's loggers plus the app/middleware loggers via the root
    logger — goes to a size-bounded rotating file under the writable data dir.
    This is what makes the windowed ``console=False`` service build (ADR-0047 §8)
    viable: there ``sys.stdout``/``sys.stderr`` are ``None``, so uvicorn's default
    config (which streams to ``ext://sys.stdout``) and Python's lastResort stderr
    handler would both crash on ``None.write`` — and a service with no console
    would die with no diagnostics. Routing to a file gives the service real logs.

    When a usable console exists (dev / source run) logs also echo to stdout.
    ``console`` defaults to whether ``sys.stdout`` is a real stream; tests pass it
    explicitly to exercise both shapes without mutating the global stream.
    """
    if console is None:
        console = sys.stdout is not None
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers: dict[str, dict] = {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(log_dir / "backend.log"),
            # Bounded so a long-running self-hosted service can't grow logs
            # without limit (ENGINEERING_RULES §12): ~5 MB × 3 backups.
            "maxBytes": 5_000_000,
            "backupCount": 3,
            "encoding": "utf-8",
            "formatter": "plain",
            "level": "INFO",
        }
    }
    active = ["file"]
    if console:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "plain",
            "level": "INFO",
        }
        active.append("console")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
        },
        "handlers": handlers,
        # Root catches the app + middleware loggers (they have no own handlers).
        "root": {"handlers": active, "level": "INFO"},
        "loggers": {
            # uvicorn ships its own handlers; repoint them at ours and stop
            # propagation so its lines aren't also re-emitted via the root logger.
            "uvicorn": {"handlers": active, "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": active, "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": active, "level": "INFO", "propagate": False},
        },
    }


def main() -> None:
    import logging.config

    data_dir = configure_environment()
    # Configure logging to a rotating file under the data dir BEFORE importing the
    # app, so the console=False service build (sys.stdout/stderr None) never falls
    # through to logging's lastResort stderr handler, and startup/import-time
    # diagnostics are captured. See _build_log_config + ADR-0047 §8.
    logging.config.dictConfig(_build_log_config(data_dir / "logs"))
    if _run_maintenance_action(data_dir):
        return
    host = os.getenv("TICKETBOX_HOST", "127.0.0.1")
    port = int(os.getenv("TICKETBOX_PORT", "8000"))
    validated_runtime_junction = _assert_runtime_data_root_authority(data_dir)
    _assert_bootstrap_recovery_not_pending(validated_runtime_junction)

    # Import the app object directly (not the "app.main:app" string form):
    # uvicorn's string import re-resolves the module via importlib, which is
    # unreliable in a frozen bundle and masks real import errors as
    # "Could not import module". Passing the object also makes any failure in
    # the app's import graph surface here with a real traceback.
    import uvicorn

    from app.main import app as fastapi_app

    # console=False (ADR-0047 §8 service build) gives a windowed PyInstaller
    # process no stdout/stderr — ``sys.stdout`` is None and ``.write`` would
    # raise. Guard so the same entrypoint is safe in both the console build and
    # the windowed-service build (the file log records startup either way).
    if sys.stdout is not None:
        print(f"Ticketbox backend  ·  data: {data_dir}  ·  http://{host}:{port}", flush=True)

    # ADR-0047 §Confirmation: keep a bounded drain for service builds. Slice 2-D
    # verified the current console=False Shawl service build does not receive
    # Ctrl-C/SIGINT and falls back to Shawl's stop-timeout kill; the app writes
    # no business state during lifespan shutdown, while PG keeps durability.
    shutdown_timeout = int(os.getenv("TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS", "25"))
    guarded_app = _InstallerRuntimeRecoveryGuard(
        fastapi_app,
        _installer_runtime_recovery_guard_path(),
    )
    uvicorn.run(
        guarded_app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        # Logging is already configured above (file + optional console). Pass
        # None so uvicorn does NOT re-apply its default config, which streams to
        # ext://sys.stdout and would crash under console=False.
        log_config=None,
        timeout_graceful_shutdown=shutdown_timeout,
    )


if __name__ == "__main__":
    import multiprocessing

    # PyInstaller hardening (ADR-0047 §8): a frozen build that ever spawns a
    # child process (e.g. a future multi-worker uvicorn) would otherwise
    # re-execute the bootloader and recursively launch the app. No-op today
    # (workers=1, app object passed directly), required before any spawn lands.
    multiprocessing.freeze_support()
    main()
