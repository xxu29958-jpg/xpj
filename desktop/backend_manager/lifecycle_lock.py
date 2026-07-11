"""Windows installer lifecycle exclusion for elevated service controls."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_CSIDL_PROGRAM_FILES_COMMON = 0x002B
_SHGFP_TYPE_CURRENT = 0
_GENERIC_READ_WRITE = 0xC0000000
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80
_ERROR_SHARING_VIOLATION = 32
_ERROR_LOCK_VIOLATION = 33
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class LifecycleBusyError(RuntimeError):
    """Another installer or lifecycle controller owns the machine lock."""


def _common_program_files() -> Path:
    if os.name != "nt":
        raise OSError("installed lifecycle controls require Windows")
    shell32 = ctypes.WinDLL("Shell32", use_last_error=True)
    shell32.SHGetFolderPathW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
    ]
    shell32.SHGetFolderPathW.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    result = shell32.SHGetFolderPathW(
        None,
        _CSIDL_PROGRAM_FILES_COMMON,
        None,
        _SHGFP_TYPE_CURRENT,
        buffer,
    )
    if result != 0 or not buffer.value:
        raise OSError(f"cannot resolve Common Program Files (HRESULT=0x{result & 0xFFFFFFFF:08x})")
    return Path(buffer.value)


def _assert_native_windows_process() -> None:
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.IsWow64Process.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    kernel32.IsWow64Process.restype = ctypes.c_int
    wow64 = ctypes.c_int()
    if not kernel32.IsWow64Process(kernel32.GetCurrentProcess(), ctypes.byref(wow64)):
        raise OSError(f"cannot verify manager process bitness (Windows error={ctypes.get_last_error()})")
    if wow64.value:
        raise OSError("32-bit manager cannot share the 64-bit installer lifecycle lock")


def _open_exclusive(path: Path) -> int:
    _assert_native_windows_process()
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ_WRITE,
        0,
        None,
        _OPEN_ALWAYS,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        if error in {_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION}:
            raise LifecycleBusyError("Ticketbox installer lifecycle is busy")
        raise OSError(error, f"cannot acquire installer lifecycle lock: {path}")
    return int(handle)


def _close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    if not kernel32.CloseHandle(ctypes.c_void_p(handle)):
        raise OSError(f"cannot release installer lifecycle lock (Windows error={ctypes.get_last_error()})")


def installer_lifecycle_lock_path() -> Path:
    return _common_program_files() / "Ticketbox" / "installer-lifecycle.lock"


@contextmanager
def hold_installer_lifecycle_lock(*, path: Path | None = None) -> Iterator[None]:
    path = path or installer_lifecycle_lock_path()
    if not path.parent.is_dir():
        raise OSError(f"installer lifecycle directory is missing: {path.parent}")
    handle = _open_exclusive(path)
    try:
        yield
    finally:
        _close_handle(handle)
