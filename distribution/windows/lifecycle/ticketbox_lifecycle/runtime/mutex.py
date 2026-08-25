from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_security_native as native

_FILE_SHARE_NONE = 0
_GENERIC_READ_WRITE = 0xC0000000
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_LOCK_SDDL = "O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class ThreadMutex:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if not self._lock.acquire(blocking=True, timeout=30):
            raise LifecycleError("mutex_timeout", "could not acquire TicketboxLifecycle mutex")

    def release(self) -> None:
        self._lock.release()


class WindowsFileMutex:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: int | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self._handle = _open_protected_lock_file(self._path)

    def release(self) -> None:
        if self._handle is None:
            return
        _close_handle(self._handle)
        self._handle = None


def os_mutex(path: Path) -> ThreadMutex | WindowsFileMutex:
    import os

    if os.name == "nt":
        return WindowsFileMutex(path)
    return ThreadMutex()


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.DWORD),
        ("security_descriptor", ctypes.c_void_p),
        ("inherit_handle", wintypes.BOOL),
    )


def _open_protected_lock_file(path: Path) -> int:
    native.reject_reparse_components(path)
    if not path.parent.is_dir():
        raise LifecycleError("lock_root_missing", "Ticketbox control directory is missing")
    native.require_trusted_owner(
        path.parent,
        code="lock_root_untrusted",
        message="Ticketbox control directory has an untrusted owner",
    )
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        _LOCK_SDDL,
        1,
        ctypes.byref(descriptor),
        None,
    ):
        raise LifecycleError("lock_security_failed", "cannot build lock-file security policy")
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    try:
        handle = kernel32.CreateFileW(
            str(path),
            _GENERIC_READ_WRITE,
            _FILE_SHARE_NONE,
            ctypes.byref(attributes),
            _OPEN_ALWAYS,
            _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
    finally:
        kernel32.LocalFree(descriptor)
    if handle == _INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        code = "lifecycle_busy" if error in {32, 33} else "lock_open_failed"
        raise LifecycleError(code, f"cannot acquire Ticketbox lifecycle lease (Windows error {error})")
    retained = int(handle)
    try:
        native.reject_reparse_components(path)
        native.require_trusted_owner(
            path,
            code="lock_file_untrusted",
            message="Ticketbox lifecycle lock has an untrusted owner",
        )
        if native._object_dacl_sddl(path) != native._canonical_dacl_sddl(_LOCK_SDDL):
            raise LifecycleError("lock_file_untrusted", "Ticketbox lifecycle lock ACL is not exact")
    except Exception:
        _close_handle(retained)
        raise
    return retained


def _close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)
