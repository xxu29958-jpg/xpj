"""Retained-handle Windows file reads that reject reparse and replacement."""

from __future__ import annotations

import ctypes
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from backend_manager.runtime import RuntimeControlError

_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_FILE_OBJECT = 1
_SDDL_REVISION_1 = 1
_GENERIC_READ = 0x80000000
_GENERIC_READ_WRITE = 0xC0000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_ERROR_INSUFFICIENT_BUFFER = 122


def reject_reparse_components(path: Path) -> None:
    cursor = Path(os.path.abspath(path))
    while True:
        try:
            observed = cursor.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise RuntimeControlError(f"无法检查路径组件：{cursor}") from exc
        else:
            attributes = int(getattr(observed, "st_file_attributes", 0))
            if stat.S_ISLNK(observed.st_mode) or attributes & 0x400:
                raise RuntimeControlError(f"路径包含重解析点：{cursor}")
        parent = cursor.parent
        if parent == cursor:
            return
        cursor = parent


def lookup_account_sid(account: str) -> str:
    advapi = ctypes.WinDLL("Advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    advapi.LookupAccountNameW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
    ]
    advapi.LookupAccountNameW.restype = ctypes.c_int
    advapi.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    advapi.ConvertSidToStringSidW.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    sid_size = ctypes.c_ulong()
    domain_size = ctypes.c_ulong()
    sid_use = ctypes.c_ulong()
    advapi.LookupAccountNameW(
        None,
        account,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    )
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or sid_size.value == 0:
        raise RuntimeControlError("无法解析 Windows 帐户 SID。")
    sid = ctypes.create_string_buffer(sid_size.value)
    domain = ctypes.create_unicode_buffer(domain_size.value)
    if not advapi.LookupAccountNameW(
        None,
        account,
        sid,
        ctypes.byref(sid_size),
        domain,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    ):
        raise RuntimeControlError("无法解析 Windows 帐户 SID。")
    text = ctypes.c_wchar_p()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise RuntimeControlError("无法格式化 Windows 帐户 SID。")
    try:
        return str(text.value)
    finally:
        kernel32.LocalFree(text)


def file_security_descriptor(path: Path) -> tuple[str, str]:
    advapi = ctypes.WinDLL("Advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    advapi.GetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    result = advapi.GetNamedSecurityInfoW(
        str(path),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise RuntimeControlError(f"无法读取文件安全描述符（Windows error={result}）。")
    sid_text = ctypes.c_wchar_p()
    sddl_text = ctypes.c_wchar_p()
    try:
        if not advapi.ConvertSidToStringSidW(owner, ctypes.byref(sid_text)):
            raise RuntimeControlError("无法读取文件 owner SID。")
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            _SDDL_REVISION_1,
            _DACL_SECURITY_INFORMATION,
            ctypes.byref(sddl_text),
            None,
        ):
            raise RuntimeControlError("无法读取文件 DACL。")
        return sid_text.value, sddl_text.value
    finally:
        if sid_text:
            kernel32.LocalFree(sid_text)
        if sddl_text:
            kernel32.LocalFree(sddl_text)
        if descriptor:
            kernel32.LocalFree(descriptor)


@contextmanager
def open_exclusive_file(path: Path, *, writable: bool) -> Iterator[BinaryIO]:
    if os.name != "nt":
        with path.open("r+b" if writable else "rb") as stream:
            yield stream
        return
    import msvcrt

    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
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
        _GENERIC_READ_WRITE if writable else _GENERIC_READ,
        0 if writable else _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if not handle or handle == invalid_handle:
        raise RuntimeControlError(f"无法独占打开文件（Windows error={ctypes.get_last_error()}）。")
    fd = -1
    try:
        flags = (os.O_RDWR if writable else os.O_RDONLY) | os.O_BINARY
        fd = msvcrt.open_osfhandle(handle, flags)
        handle = None
        with os.fdopen(fd, "r+b" if writable else "rb", closefd=True) as stream:
            fd = -1
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise RuntimeControlError("文件必须是单链接普通文件。")
            _require_exact_handle_path(kernel32, stream, path)
            yield stream
    finally:
        if fd >= 0:
            os.close(fd)
        if handle:
            kernel32.CloseHandle(handle)


def _require_exact_handle_path(kernel32: object, stream: BinaryIO, expected_path: Path) -> None:
    import msvcrt

    kernel32.GetFinalPathNameByHandleW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_ulong
    handle = msvcrt.get_osfhandle(stream.fileno())
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if length == 0 or length >= len(buffer):
        raise RuntimeControlError("无法确认文件最终路径。")
    final_path = buffer.value[4:] if buffer.value.startswith("\\\\?\\") else buffer.value
    if os.path.normcase(os.path.abspath(final_path)) != os.path.normcase(os.path.abspath(expected_path)):
        raise RuntimeControlError("文件句柄指向了不同路径。")
