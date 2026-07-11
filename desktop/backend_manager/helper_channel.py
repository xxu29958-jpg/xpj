"""Native validation and in-place IO for the UAC helper result channel."""

from __future__ import annotations

import ctypes
import os
import re
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
_GENERIC_READ_WRITE = 0xC0000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_SID_PATTERN = re.compile(r"S-1-(?:[0-9]+-)+[0-9]+\Z", re.IGNORECASE)
_ACE_PATTERN = re.compile(r"\(([^()]*)\)")


def channel_file_identity(stream: BinaryIO) -> str:
    info = os.fstat(stream.fileno())
    return f"{info.st_dev:x}:{info.st_ino:x}"


def require_sid(value: str) -> str:
    if not _SID_PATTERN.fullmatch(value):
        raise RuntimeControlError("管理员结果通道 owner SID 格式无效。")
    return value


def validate_exact_file_security(path: Path, caller_sid: str, *, directory: bool = False) -> None:
    """Require caller ownership and one protected full-control ACE per trusted principal."""
    if os.name != "nt":
        return
    owner_sid, sddl = _security_descriptor(path)
    if owner_sid.casefold() != require_sid(caller_sid).casefold():
        raise RuntimeControlError("管理员结果通道 owner 与发起用户不一致。")
    dacl = sddl.partition("D:")[2]
    if not dacl.startswith("P"):
        raise RuntimeControlError("管理员结果通道 ACL 未禁止继承。")
    aces = _ACE_PATTERN.findall(dacl)
    expected = {"SY", "BA", caller_sid.upper()}
    actual: set[str] = set()
    if len(aces) != len(expected):
        raise RuntimeControlError("管理员结果通道 ACL 包含额外主体。")
    for raw in aces:
        fields = raw.split(";")
        expected_flags = "OICI" if directory else ""
        if len(fields) != 6 or fields[0] != "A" or fields[1] != expected_flags or fields[2] != "FA":
            raise RuntimeControlError("管理员结果通道 ACL 不是精确 FullControl allow 规则。")
        principal = fields[5].upper()
        if principal not in expected or principal in actual:
            raise RuntimeControlError("管理员结果通道 ACL 主体不符合 caller/SYSTEM/Administrators 契约。")
        actual.add(principal)
    if actual != expected:
        raise RuntimeControlError("管理员结果通道 ACL 不完整。")


def _security_descriptor(path: Path) -> tuple[str, str]:
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
        raise RuntimeControlError(f"无法读取管理员结果通道安全描述符（Windows error={result}）。")
    sid_text = ctypes.c_wchar_p()
    sddl_text = ctypes.c_wchar_p()
    try:
        if not advapi.ConvertSidToStringSidW(owner, ctypes.byref(sid_text)):
            raise RuntimeControlError("无法读取管理员结果通道 owner SID。")
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            _SDDL_REVISION_1,
            _DACL_SECURITY_INFORMATION,
            ctypes.byref(sddl_text),
            None,
        ):
            raise RuntimeControlError("无法读取管理员结果通道 DACL。")
        return sid_text.value, sddl_text.value
    finally:
        if sid_text:
            kernel32.LocalFree(sid_text)
        if sddl_text:
            kernel32.LocalFree(sddl_text)
        if descriptor:
            kernel32.LocalFree(descriptor)


@contextmanager
def open_exclusive_channel(path: Path) -> Iterator[BinaryIO]:
    """Open the already-created file without following a final reparse point or allowing swaps."""
    if os.name != "nt":
        with path.open("r+b") as stream:
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
        _GENERIC_READ_WRITE,
        0,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if not handle or handle == invalid_handle:
        raise RuntimeControlError(f"无法独占打开管理员结果通道（Windows error={ctypes.get_last_error()}）。")
    fd = -1
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        handle = None
        with os.fdopen(fd, "r+b", closefd=True) as stream:
            fd = -1
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise RuntimeControlError("管理员结果通道必须是单链接普通文件。")
            _require_exact_handle_path(kernel32, stream, path)
            yield stream
    finally:
        if fd >= 0:
            os.close(fd)
        if handle:
            kernel32.CloseHandle(handle)


def _require_exact_handle_path(kernel32, stream: BinaryIO, expected_path: Path) -> None:
    import msvcrt

    kernel32.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong]
    kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_ulong
    handle = msvcrt.get_osfhandle(stream.fileno())
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if length == 0 or length >= len(buffer):
        raise RuntimeControlError("无法确认管理员结果通道最终路径。")
    final_path = buffer.value
    if final_path.startswith("\\\\?\\"):
        final_path = final_path[4:]
    expected = os.path.normcase(os.path.abspath(expected_path))
    if os.path.normcase(os.path.abspath(final_path)) != expected:
        raise RuntimeControlError("管理员结果通道句柄指向了不同路径。")
