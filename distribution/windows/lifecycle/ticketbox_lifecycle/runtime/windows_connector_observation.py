"""Prove the exact SCM process image and fixed loopback metrics listener."""

from __future__ import annotations

import ctypes
import os
import socket
from ctypes import wintypes
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.connector_profile import METRICS_HOST, METRICS_PORT


class _Tcp4(ctypes.Structure):
    _fields_ = [(key, wintypes.DWORD) for key in ("state", "local", "port", "remote", "remote_port", "pid")]


class _Tcp6(ctypes.Structure):
    _fields_ = [("local", ctypes.c_ubyte * 16), ("scope", wintypes.DWORD), ("port", wintypes.DWORD),
        ("remote", ctypes.c_ubyte * 16), ("remote_scope", wintypes.DWORD), ("remote_port", wintypes.DWORD),
        ("state", wintypes.DWORD), ("pid", wintypes.DWORD)]


def metrics_listeners() -> list[tuple[str, int]]:
    api = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    api.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
        wintypes.ULONG, ctypes.c_int, wintypes.ULONG)
    api.restype = wintypes.DWORD
    result = []
    for family, model in ((socket.AF_INET, _Tcp4), (socket.AF_INET6, _Tcp6)):
        size = wintypes.DWORD()
        error = api(None, ctypes.byref(size), False, family, 3, 0)
        if error not in {0, 122} or not 4 <= size.value <= 8 * 1024 * 1024:
            raise LifecycleError("connector_port_unobservable", "cannot inspect the connector diagnostic port")
        buffer = ctypes.create_string_buffer(size.value)
        if api(buffer, ctypes.byref(size), False, family, 3, 0):
            raise LifecycleError("connector_port_unobservable", "diagnostic listener changed during observation")
        count = wintypes.DWORD.from_buffer(buffer).value
        if 4 + count * ctypes.sizeof(model) > len(buffer):
            raise LifecycleError("connector_port_unobservable", "invalid diagnostic listener table")
        for index in range(count):
            row = model.from_buffer(buffer, 4 + index * ctypes.sizeof(model))
            if socket.ntohs(row.port & 0xFFFF) == METRICS_PORT:
                address = socket.inet_ntop(family, row.local.to_bytes(4, "little") if family == socket.AF_INET else bytes(row.local))
                result.append((address, int(row.pid)))
    return result


def require_process_image(pid: int, expected: Path) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        raise LifecycleError("connector_process_unobservable", "SCM process is no longer observable")
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            raise LifecycleError("connector_process_unobservable", "SCM process image cannot be observed")
        if os.path.normcase(buffer.value) != os.path.normcase(str(expected)):
            raise LifecycleViolation("connector_process_mismatch", "SCM process is not the installed connector executable")
    finally:
        kernel.CloseHandle(process)


def require_metrics_owner(pid: int | None, *, required: bool = False) -> None:
    listeners = metrics_listeners()
    if any(address != METRICS_HOST or owner != pid for address, owner in listeners):
        raise LifecycleViolation("connector_metrics_collision", "diagnostic port is owned by another process or exposed beyond loopback")
    if required and listeners != [(METRICS_HOST, pid)]:
        raise LifecycleError("connector_metrics_pending", "the exact connector diagnostic listener is not yet available")
