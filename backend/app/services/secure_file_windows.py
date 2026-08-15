"""Low-level Windows ACL and file-handle operations for secure files."""

from __future__ import annotations

import contextlib
import ctypes
import os
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path

_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_TOKEN_GROUPS = 2
_SE_GROUP_ENABLED = 0x00000004
_SE_GROUP_USE_FOR_DENY_ONLY = 0x00000010
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INSUFFICIENT_BUFFER = 122
_GENERIC_WRITE = 0x40000000
_GENERIC_READ = 0x80000000
_READ_CONTROL = 0x00020000
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_SHARE_READ = 0x00000001
_FILE_FLAG_WRITE_THROUGH = 0x80000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_SDDL_REVISION_1 = 1
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_DACL_PROTECTED = 0x1000
_ACL_SIZE_INFORMATION_CLASS = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_INHERITED_ACE = 0x10
_FILE_ALL_ACCESS = 0x001F01FF
_INVALID_HANDLE = ctypes.c_void_p(-1).value
SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
FILE_ALL_ACCESS = _FILE_ALL_ACCESS
FILE_GENERIC_READ_EXECUTE = 0x001200A9


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("user", _SidAndAttributes)]


class _TokenGroups(ctypes.Structure):
    _fields_ = [
        ("group_count", wintypes.DWORD),
        ("groups", _SidAndAttributes * 1),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("security_descriptor", ctypes.c_void_p),
        ("inherit_handle", wintypes.BOOL),
    ]


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("low", wintypes.DWORD),
        ("high", wintypes.DWORD),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("ace_count", wintypes.DWORD),
        ("acl_bytes_in_use", wintypes.DWORD),
        ("acl_bytes_free", wintypes.DWORD),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("ace_type", ctypes.c_ubyte),
        ("ace_flags", ctypes.c_ubyte),
        ("ace_size", wintypes.WORD),
    ]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ("header", _AceHeader),
        ("mask", wintypes.DWORD),
        ("sid_start", wintypes.DWORD),
    ]


def _configure_advapi32(advapi32: object) -> None:
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]


def _configure_kernel32(kernel32: object) -> None:
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.MoveFileExW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    kernel32.MoveFileExW.restype = wintypes.BOOL


def windows_apis() -> tuple[object, object]:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_advapi32(advapi32)
    _configure_kernel32(kernel32)
    return advapi32, kernel32


def process_start_filetime(
    process_id: int,
    *,
    apis: tuple[object, object],
) -> tuple[int, int]:
    """Return the immutable Windows creation FILETIME for one live process."""

    if os.name != "nt":
        raise OSError("Windows process identity is unavailable")
    if isinstance(process_id, bool) or process_id <= 0:
        raise ValueError("process id must be a positive integer")
    _advapi32, kernel32 = apis
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        process_id,
    )
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    created = _FileTime()
    exited = _FileTime()
    kernel = _FileTime()
    user = _FileTime()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(created.high), int(created.low)
    finally:
        kernel32.CloseHandle(handle)


def current_process_sid(advapi32: object, kernel32: object) -> str:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    sid_string = wintypes.LPWSTR()
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(required))
        if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_USER,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        if not advapi32.ConvertSidToStringSidW(
            token_user.user.sid, ctypes.byref(sid_string)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return str(sid_string.value)
    finally:
        if sid_string:
            kernel32.LocalFree(sid_string)
        kernel32.CloseHandle(token)


def _select_dedicated_service_sid(groups: tuple[tuple[str, int], ...]) -> str:
    candidates = {
        sid
        for sid, attributes in groups
        if attributes & _SE_GROUP_ENABLED
        and not attributes & _SE_GROUP_USE_FOR_DENY_ONLY
        and len(sid.split("-")) == 9
        and sid.split("-")[:4] == ["S", "1", "5", "80"]
        and all(part.isdecimal() for part in sid.split("-")[4:])
    }
    if len(candidates) != 1:
        raise PermissionError(
            "runtime projection requires one enabled dedicated Windows service SID"
        )
    return next(iter(candidates))


def current_process_service_sid(advapi32: object, kernel32: object) -> str:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_GROUPS, None, 0, ctypes.byref(required))
        if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_GROUPS,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        token_groups = ctypes.cast(buffer, ctypes.POINTER(_TokenGroups)).contents
        array_type = _SidAndAttributes * int(token_groups.group_count)
        groups = ctypes.cast(
            ctypes.addressof(token_groups) + _TokenGroups.groups.offset,
            ctypes.POINTER(array_type),
        ).contents
        observed: list[tuple[str, int]] = []
        for group in groups:
            sid_string = wintypes.LPWSTR()
            try:
                if not advapi32.ConvertSidToStringSidW(
                    group.sid, ctypes.byref(sid_string)
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                observed.append((str(sid_string.value), int(group.attributes)))
            finally:
                if sid_string:
                    kernel32.LocalFree(sid_string)
        return _select_dedicated_service_sid(tuple(observed))
    finally:
        kernel32.CloseHandle(token)


def _protected_sddl(sid: str) -> str:
    trustees = tuple(dict.fromkeys((sid, SYSTEM_SID, ADMINISTRATORS_SID)))
    rules = "".join(f"(A;;FA;;;{trustee})" for trustee in trustees)
    return f"O:{sid}D:P{rules}"


def protected_security_descriptor(advapi32: object, sid: str) -> ctypes.c_void_p:
    descriptor = ctypes.c_void_p()
    sddl = _protected_sddl(sid)
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        _SDDL_REVISION_1,
        ctypes.byref(descriptor),
        None,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return descriptor


def _sid_string(advapi32: object, kernel32: object, sid: ctypes.c_void_p) -> str:
    value = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return str(value.value)
    finally:
        kernel32.LocalFree(value)


def _windows_final_path(kernel32: object, handle: wintypes.HANDLE) -> str:
    capacity = 512
    while True:
        buffer = ctypes.create_unicode_buffer(capacity)
        length = kernel32.GetFinalPathNameByHandleW(handle, buffer, capacity, 0)
        if length == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        if length < capacity:
            value = buffer.value
            if value.startswith("\\\\?\\UNC\\"):
                return "\\\\" + value[8:]
            if value.startswith("\\\\?\\"):
                return value[4:]
            return value
        capacity = length + 1


def validate_file_identity(
    kernel32: object,
    handle: wintypes.HANDLE,
    path: Path,
) -> Path:
    info = _FileAttributeTagInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if info.attributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError("protected file must be a plain non-reparse file")
    lexical = os.path.normpath(os.path.abspath(path))
    final = os.path.normpath(_windows_final_path(kernel32, handle))
    if os.path.normcase(lexical) != os.path.normcase(final):
        raise OSError("protected file path traverses a reparse point")
    return Path(lexical)


def validate_file_acl(
    advapi32: object,
    kernel32: object,
    handle: wintypes.HANDLE,
    *,
    owner_sids: frozenset[str] | None = None,
    access_rules: dict[str, int] | None = None,
) -> None:
    from app.services import secure_file_windows_acl

    secure_file_windows_acl.validate_file_acl(
        advapi32,
        kernel32,
        handle,
        owner_sids=owner_sids,
        access_rules=access_rules,
    )


@contextlib.contextmanager
def hold_protected_file(
    path: Path,
    *,
    apis: tuple[object, object],
    owner_sids: frozenset[str] | None = None,
    access_rules: dict[str, int] | None = None,
) -> Iterator[Path]:
    advapi32, kernel32 = apis
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ | _READ_CONTROL,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        resolved = validate_file_identity(kernel32, handle, path)
        validate_file_acl(
            advapi32,
            kernel32,
            handle,
            owner_sids=owner_sids,
            access_rules=access_rules,
        )
        yield resolved
    finally:
        kernel32.CloseHandle(handle)


def _write_file(
    kernel32: object,
    path: Path,
    payload: bytes,
    descriptor: ctypes.c_void_p,
) -> None:
    attributes = _SecurityAttributes(
        ctypes.sizeof(_SecurityAttributes),
        descriptor,
        False,
    )
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_WRITE,
        0,
        ctypes.byref(attributes),
        _CREATE_NEW,
        _FILE_FLAG_WRITE_THROUGH,
        None,
    )
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        written = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(payload)
        if not kernel32.WriteFile(
            handle, buffer, len(payload), ctypes.byref(written), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value != len(payload):
            raise OSError("short write while creating protected file")
        if not kernel32.FlushFileBuffers(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


def write_protected_file(
    path: Path,
    payload: bytes,
    *,
    apis: tuple[object, object],
) -> None:
    advapi32, kernel32 = apis
    descriptor = protected_security_descriptor(
        advapi32,
        current_process_sid(advapi32, kernel32),
    )
    try:
        _write_file(kernel32, path, payload, descriptor)
    finally:
        kernel32.LocalFree(descriptor)
