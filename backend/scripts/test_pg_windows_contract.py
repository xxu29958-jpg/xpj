"""Windows parent, mutex, temporary-path, and consumer-lease contracts."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import re
import sys
import threading
from collections.abc import Callable, Iterator, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import URL, make_url

from scripts.test_pg_disposable_file import _remove_disposable_test_files
from scripts.test_pg_protected_file import (
    create_protected_shared_lock_file,
    ensure_protected_directory,
)
from scripts.test_pg_url_contract import _dialect_connection_args
from scripts.test_pg_windows_path_contract import (
    _lexical_absolute_path,
    _windows_directory_path_lease,
)

_AUTHORITY_LOST_EXIT_CODE = 3
_CONSUMER_LEASE_KIND = "xiaopiaojia-test-postgres-consumer"
_CONSUMER_LEASE_TIMEOUT_MS = 300_000
_CONSUMER_LEASE_LOCK_OFFSET = 1 << 30
_PARENT_WATCHDOG_LOCK = threading.Lock()
_PARENT_WATCHDOG_STARTED = False
WINDOWS_PARENT_AUTHORITY_PID_ENV = "XPJ_TEST_PARENT_AUTHORITY_PID"
WINDOWS_PARENT_AUTHORITY_CREATED_ENV = "XPJ_TEST_PARENT_AUTHORITY_CREATED"


def _windows_kernel32() -> object:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _windows_process_kernel32() -> object:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForMultipleObjects.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _windows_parent_process_chain() -> tuple[int, ...]:
    from ctypes import wintypes

    class ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "Cannot inspect the test process tree")
    try:
        parents: dict[int, int] = {}
        entry = ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    chain: list[int] = []
    seen = {os.getpid()}
    parent_id = parents.get(os.getpid(), 0)
    while parent_id > 0 and parent_id not in seen:
        chain.append(parent_id)
        seen.add(parent_id)
        parent_id = parents.get(parent_id, 0)
    if not chain:
        raise RuntimeError("Disposable test process has no parent authority")
    return tuple(chain)


def _windows_process_created_filetime(kernel32: object, handle: object) -> int:
    from ctypes import wintypes

    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not kernel32.GetProcessTimes(
        handle,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise OSError(ctypes.get_last_error(), "Cannot identify the test process generation")
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


def _windows_parent_process_handle(kernel32: object) -> object:
    child_created = _windows_process_created_filetime(
        kernel32,
        kernel32.GetCurrentProcess(),
    )
    raw_parent_id = os.environ.get(WINDOWS_PARENT_AUTHORITY_PID_ENV, "").strip()
    raw_parent_created = os.environ.get(
        WINDOWS_PARENT_AUTHORITY_CREATED_ENV,
        "",
    ).strip()
    if bool(raw_parent_id) != bool(raw_parent_created):
        raise RuntimeError("Disposable test process parent authority is incomplete")
    if raw_parent_id:
        try:
            parent_id = int(raw_parent_id)
            expected_parent_created = int(raw_parent_created)
        except ValueError as exc:
            raise RuntimeError(
                "Disposable test process parent authority is malformed"
            ) from exc
        if parent_id <= 0 or expected_parent_created <= 0:
            raise RuntimeError("Disposable test process parent authority is malformed")
    else:
        parent_id = _windows_parent_process_chain()[0]
        expected_parent_created = None
    parent_handle = kernel32.OpenProcess(
        0x00100000 | 0x00001000,
        False,
        parent_id,
    )
    if not parent_handle:
        raise RuntimeError("Disposable test process parent is already unavailable")
    try:
        parent_created = _windows_process_created_filetime(kernel32, parent_handle)
    except OSError:
        kernel32.CloseHandle(parent_handle)
        raise
    if (
        parent_created >= child_created
        or (
            expected_parent_created is not None
            and parent_created != expected_parent_created
        )
    ):
        kernel32.CloseHandle(parent_handle)
        raise RuntimeError("Disposable test process parent generation was reused")
    return parent_handle


def bind_windows_child_authority(
    environment: MutableMapping[str, str],
) -> None:
    """Bind descendants to this exact process generation, across launcher wrappers."""
    if os.name != "nt":
        return
    kernel32 = _windows_process_kernel32()
    created = _windows_process_created_filetime(
        kernel32,
        kernel32.GetCurrentProcess(),
    )
    environment[WINDOWS_PARENT_AUTHORITY_PID_ENV] = str(os.getpid())
    environment[WINDOWS_PARENT_AUTHORITY_CREATED_ENV] = str(created)


def _abort_disposable_test_process(message: str) -> None:
    try:
        cleanup_failures = _remove_disposable_test_files()
        try:
            print(message, file=sys.stderr, flush=True)
            for path in cleanup_failures:
                print(
                    f"Could not remove disposable credential file before exit: {path}",
                    file=sys.stderr,
                    flush=True,
                )
        except (OSError, ValueError):
            pass
    finally:
        os._exit(_AUTHORITY_LOST_EXIT_CODE)


def _watch_windows_parent_handle(
    kernel32: object,
    parent_handle: object,
    *,
    label: str,
    abort_process: Callable[[str], None],
) -> None:
    try:
        result = kernel32.WaitForSingleObject(parent_handle, 0xFFFFFFFF)
    finally:
        kernel32.CloseHandle(parent_handle)
    if result == 0:
        abort_process(f"Lost {label} parent process; aborting this disposable test process.")
        return
    abort_process(f"Cannot monitor {label} parent process; aborting this disposable test process.")


def start_windows_parent_watchdog(
    *,
    label: str,
    abort_process: Callable[[str], None] | None = None,
) -> None:
    """Exit a disposable Windows process when its exact direct-parent generation dies."""

    global _PARENT_WATCHDOG_STARTED

    if os.name != "nt":
        return
    with _PARENT_WATCHDOG_LOCK:
        if _PARENT_WATCHDOG_STARTED:
            return
        kernel32 = _windows_process_kernel32()
        parent_handle = _windows_parent_process_handle(kernel32)
        abort = abort_process or _abort_disposable_test_process
        watchdog = threading.Thread(
            target=_watch_windows_parent_handle,
            kwargs={
                "kernel32": kernel32,
                "parent_handle": parent_handle,
                "label": label,
                "abort_process": abort,
            },
            name=f"{label}-parent-watchdog",
            daemon=True,
        )
        try:
            watchdog.start()
        except RuntimeError:
            kernel32.CloseHandle(parent_handle)
            raise
        bind_windows_child_authority(os.environ)
        _PARENT_WATCHDOG_STARTED = True


def _acquire_windows_lifecycle_mutex(port: int, timeout_ms: int) -> tuple[object, object]:
    kernel32 = _windows_kernel32()
    handle = kernel32.CreateMutexW(None, False, f"Global\\XpjTestPostgresLifecycle-{port}")
    if not handle:
        raise OSError(ctypes.get_last_error(), "Cannot create test PostgreSQL lifecycle mutex")
    acquired = False
    try:
        result = kernel32.WaitForSingleObject(handle, timeout_ms)
        if result not in {0x00000000, 0x00000080}:
            raise RuntimeError("Timed out waiting for the test PostgreSQL lifecycle mutex")
        acquired = True
        return kernel32, handle
    finally:
        if not acquired:
            kernel32.CloseHandle(handle)


def _database_port(database_url: str | URL) -> int:
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Test consumer lease requires a PostgreSQL URL")
    raw_port = _dialect_connection_args(parsed).get("port", 5432)
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as error:
        raise ValueError("Test consumer lease PostgreSQL port is invalid") from error
    if not 1 <= port <= 65535:
        raise ValueError("Test consumer lease PostgreSQL port is invalid")
    return port


def _windows_temp_directory() -> Path:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetTempPathW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    kernel32.GetTempPathW.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetTempPathW(len(buffer), buffer)
    if length == 0 or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "Cannot resolve the Windows temp path")
    return Path(buffer.value)


def _validated_consumer_generation(
    data_directory: Path,
    authority_resolver: Callable[[], tuple[Path, str, str]],
) -> tuple[str, str]:
    resolved_directory, system_identifier, instance_id = authority_resolver()
    resolved_directory = _lexical_absolute_path(
        resolved_directory,
        label="Owned test PostgreSQL marker directory",
    )
    if resolved_directory != data_directory:
        raise RuntimeError("Owned test PostgreSQL marker moved outside its leased directory")
    if re.fullmatch(r"\d{10,20}", system_identifier) is None:
        raise RuntimeError("Test PostgreSQL consumer lease system identifier is invalid")
    if re.fullmatch(r"[0-9a-f]{32}", instance_id) is None:
        raise RuntimeError("Test PostgreSQL consumer lease instance identifier is invalid")
    return system_identifier, instance_id


def _create_consumer_lease_file(
    lease_directory: Path,
    *,
    data_directory: Path,
    port: int,
    system_identifier: str,
    instance_id: str,
) -> tuple[int, Path, int]:
    import msvcrt

    lease_path = lease_directory / f"{os.getpid()}-{uuid4().hex}.lease"
    payload = json.dumps(
        {
            "Kind": _CONSUMER_LEASE_KIND,
            "Port": port,
            "DataDirectory": str(data_directory),
            "SystemIdentifier": system_identifier,
            "InstanceId": instance_id,
            "ProcessId": os.getpid(),
            "ProcessStartedAtUtc": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor = create_protected_shared_lock_file(
        lease_path,
        label="Test PostgreSQL consumer lease",
    )
    completed = False
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Could not write the test PostgreSQL consumer lease.")
            remaining = remaining[written:]
        os.fsync(descriptor)
        lock_offset = _CONSUMER_LEASE_LOCK_OFFSET
        os.lseek(descriptor, lock_offset, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        completed = True
        return descriptor, lease_path, lock_offset
    finally:
        if not completed:
            os.close(descriptor)
            lease_path.unlink(missing_ok=True)


@contextlib.contextmanager
def windows_test_postgres_consumer_lease(
    database_url: str | URL,
    *,
    data_directory: Path,
    authority_resolver: Callable[[], tuple[Path, str, str]],
    timeout_ms: int = _CONSUMER_LEASE_TIMEOUT_MS,
) -> Iterator[Path | None]:
    """Register this process as a reader before it can touch the test cluster."""

    if os.name != "nt":
        yield None
        return

    port = _database_port(database_url)
    kernel32, lifecycle_handle = _acquire_windows_lifecycle_mutex(port, timeout_ms)
    descriptor: int | None = None
    lease_path: Path | None = None
    lock_offset: int | None = None
    path_leases = contextlib.ExitStack()
    registered = False
    try:
        data_directory = _lexical_absolute_path(
            data_directory,
            label="Test PostgreSQL data directory",
        )
        path_leases.enter_context(_windows_directory_path_lease(data_directory))
        system_identifier, instance_id = _validated_consumer_generation(
            data_directory,
            authority_resolver,
        )
        lease_directory = data_directory / ".xpj-test-postgres-consumers"
        ensure_protected_directory(
            lease_directory,
            label="Test PostgreSQL consumer lease directory",
        )
        path_leases.enter_context(_windows_directory_path_lease(lease_directory))
        descriptor, lease_path, lock_offset = _create_consumer_lease_file(
            lease_directory,
            data_directory=data_directory,
            port=port,
            system_identifier=system_identifier,
            instance_id=instance_id,
        )
        registered = True
    finally:
        kernel32.ReleaseMutex(lifecycle_handle)
        kernel32.CloseHandle(lifecycle_handle)
        if not registered:
            path_leases.close()

    try:
        yield lease_path
    finally:
        import msvcrt

        assert descriptor is not None
        assert lock_offset is not None
        try:
            os.lseek(descriptor, lock_offset, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)
            assert lease_path is not None
            lease_path.unlink(missing_ok=True)
            path_leases.close()
