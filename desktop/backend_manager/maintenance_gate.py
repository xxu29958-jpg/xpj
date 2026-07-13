"""Observe the installer-owned machine maintenance marker."""

from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Callable

_REGISTRY_PATH = r"Software\Ticketbox"
_REGISTRY_VALUE = "MaintenanceOwner"
_RECORD_SCHEMA = "ticketbox-manager-maintenance-v1"
_RECORD_PATTERN = re.compile(
    rf"{_RECORD_SCHEMA}\|([1-9][0-9]{{0,9}})\|([0-9]{{1,10}})\|([0-9]{{1,10}})\Z",
)
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_MAX_UINT32 = (1 << 32) - 1


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def _read_registry_record(*, root=None, registry_path: str = _REGISTRY_PATH) -> str | None:
    import winreg

    registry_root = winreg.HKEY_LOCAL_MACHINE if root is None else root
    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        with winreg.OpenKey(registry_root, registry_path, 0, access) as key:
            value, value_type = winreg.QueryValueEx(key, _REGISTRY_VALUE)
    except FileNotFoundError:
        return None
    if value_type != winreg.REG_SZ or not isinstance(value, str):
        raise OSError("Manager maintenance owner marker has an invalid registry type")
    return value


def _active_process_matches(process_id: int, started_high: int, started_low: int) -> bool | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE,
        False,
        process_id,
    )
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        created = _FileTime()
        exited = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        wait_result = int(kernel32.WaitForSingleObject(handle, 0))
        if wait_result == _WAIT_OBJECT_0:
            return False
        if wait_result != _WAIT_TIMEOUT:
            return None
        return created.high == started_high and created.low == started_low
    finally:
        kernel32.CloseHandle(handle)


def manager_maintenance_requested(
    *,
    record_reader: Callable[[], str | None] = _read_registry_record,
    process_matcher: Callable[[int, int, int], bool | None] = _active_process_matches,
) -> bool:
    """Trust only a protected marker bound to one live installer process."""
    if os.name != "nt":
        return False
    try:
        record = record_reader()
    except OSError:
        return True
    if record is None:
        return False
    match = _RECORD_PATTERN.fullmatch(record)
    if match is None:
        return True
    process_id, started_high, started_low = (int(value) for value in match.groups())
    if any(value > _MAX_UINT32 for value in (process_id, started_high, started_low)):
        return True
    return process_matcher(process_id, started_high, started_low) is not False
