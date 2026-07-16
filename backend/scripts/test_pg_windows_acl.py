"""Native Windows ACL helpers for PostgreSQL test authority material."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import cache
from pathlib import Path

SDDL_REVISION_1 = 1
SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
FILE_ALL_ACCESS = 0x001F01FF
TOKEN_QUERY = 0x0008
TOKEN_USER = 1
ACCESS_ALLOWED_ACE_TYPE = 0
OBJECT_INHERIT_ACE = 0x01
CONTAINER_INHERIT_ACE = 0x02
ACL_SIZE_INFORMATION = 2
SE_DACL_PROTECTED = 0x1000


class SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.DWORD),
        ("security_descriptor", wintypes.LPVOID),
        ("inherit_handle", wintypes.BOOL),
    )


class _SidAndAttributes(ctypes.Structure):
    _fields_ = (("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD))


class _TokenUser(ctypes.Structure):
    _fields_ = (("user", _SidAndAttributes),)


class _AclSizeInformation(ctypes.Structure):
    _fields_ = (
        ("ace_count", wintypes.DWORD),
        ("acl_bytes_in_use", wintypes.DWORD),
        ("acl_bytes_free", wintypes.DWORD),
    )


class _AceHeader(ctypes.Structure):
    _fields_ = (
        ("ace_type", ctypes.c_ubyte),
        ("ace_flags", ctypes.c_ubyte),
        ("ace_size", wintypes.WORD),
    )


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = (
        ("header", _AceHeader),
        ("mask", wintypes.DWORD),
        ("sid_start", wintypes.DWORD),
    )


def _bind_kernel32(kernel32: ctypes.WinDLL) -> None:
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.LPVOID,)
    kernel32.LocalFree.restype = wintypes.LPVOID
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateDirectoryW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.POINTER(SecurityAttributes),
    )
    kernel32.CreateDirectoryW.restype = wintypes.BOOL


def _bind_identity_apis(advapi32: ctypes.WinDLL) -> None:
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL


def _bind_descriptor_apis(advapi32: ctypes.WinDLL) -> None:
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    )
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = (
        wintypes.LPVOID,
        ctypes.POINTER(_AclSizeInformation),
        wintypes.DWORD,
        wintypes.DWORD,
    )
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    )
    advapi32.GetAce.restype = wintypes.BOOL


@cache
def windows_libraries() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _bind_kernel32(kernel32)
    _bind_identity_apis(advapi32)
    _bind_descriptor_apis(advapi32)
    return advapi32, kernel32


def raise_windows_error(message: str, error: int | None = None) -> None:
    raise OSError(error or ctypes.get_last_error(), message)


def _sid_string(
    sid: wintypes.LPVOID,
    *,
    advapi32: ctypes.WinDLL,
    kernel32: ctypes.WinDLL,
) -> str:
    sid_pointer = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(sid_pointer)):
        raise_windows_error("Could not render a PostgreSQL test authority SID.")
    try:
        return sid_pointer.value
    finally:
        kernel32.LocalFree(ctypes.cast(sid_pointer, wintypes.LPVOID))


@cache
def current_windows_user_sid() -> str:
    advapi32, kernel32 = windows_libraries()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_QUERY,
        ctypes.byref(token),
    ):
        raise_windows_error("Could not open the PostgreSQL test identity token.")
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
        if not size.value:
            raise_windows_error("Could not size the PostgreSQL test identity token.")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            TOKEN_USER,
            buffer,
            size,
            ctypes.byref(size),
        ):
            raise_windows_error("Could not read the PostgreSQL test identity token.")
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        return _sid_string(
            token_user.user.sid,
            advapi32=advapi32,
            kernel32=kernel32,
        )
    finally:
        kernel32.CloseHandle(token)


def _read_acl_entries(
    dacl: wintypes.LPVOID,
    *,
    advapi32: ctypes.WinDLL,
    kernel32: ctypes.WinDLL,
) -> list[tuple[str, int, int, int]]:
    size = _AclSizeInformation()
    if not advapi32.GetAclInformation(
        dacl,
        ctypes.byref(size),
        ctypes.sizeof(size),
        ACL_SIZE_INFORMATION,
    ):
        raise_windows_error("Could not size a protected PostgreSQL test DACL.")
    entries: list[tuple[str, int, int, int]] = []
    for index in range(size.ace_count):
        ace_pointer = wintypes.LPVOID()
        if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
            raise_windows_error("Could not read a protected PostgreSQL test ACE.")
        header = ctypes.cast(ace_pointer, ctypes.POINTER(_AceHeader)).contents
        if header.ace_type != ACCESS_ALLOWED_ACE_TYPE:
            entries.append(("", 0, int(header.ace_flags), int(header.ace_type)))
            continue
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(_AccessAllowedAce)).contents
        sid_pointer = wintypes.LPVOID(
            ace_pointer.value + _AccessAllowedAce.sid_start.offset
        )
        entries.append(
            (
                _sid_string(
                    sid_pointer,
                    advapi32=advapi32,
                    kernel32=kernel32,
                ),
                int(ace.mask),
                int(ace.header.ace_flags),
                int(ace.header.ace_type),
            )
        )
    return entries


def windows_security_parts(
    path: Path,
) -> tuple[str, bool, list[tuple[str, int, int, int]]]:
    advapi32, kernel32 = windows_libraries()
    descriptor = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        SE_FILE_OBJECT,
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise_windows_error("Could not read a protected PostgreSQL test file ACL.", result)
    try:
        actual_owner = _sid_string(
            owner,
            advapi32=advapi32,
            kernel32=kernel32,
        )
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(
            descriptor,
            ctypes.byref(control),
            ctypes.byref(revision),
        ):
            raise_windows_error("Could not inspect a protected PostgreSQL test DACL.")
        entries = (
            _read_acl_entries(dacl, advapi32=advapi32, kernel32=kernel32)
            if dacl
            else []
        )
        return actual_owner, bool(control.value & SE_DACL_PROTECTED), entries
    finally:
        kernel32.LocalFree(descriptor)
