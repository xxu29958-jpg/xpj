"""Atomic protected-file helpers for PostgreSQL test authority material."""

from __future__ import annotations

import ctypes
import os
import stat
from ctypes import wintypes
from functools import cache
from pathlib import Path

_SDDL_REVISION_1 = 1
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_GENERIC_WRITE = 0x40000000
_CREATE_NEW = 1
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_WRITE_THROUGH = 0x80000000
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.DWORD),
        ("security_descriptor", wintypes.LPVOID),
        ("inherit_handle", wintypes.BOOL),
    )


class _SidAndAttributes(ctypes.Structure):
    _fields_ = (("sid", wintypes.LPVOID), ("attributes", wintypes.DWORD))


class _TokenUser(ctypes.Structure):
    _fields_ = (("user", _SidAndAttributes),)


@cache
def _windows_libraries() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.LPVOID,)
    kernel32.LocalFree.restype = wintypes.LPVOID
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
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    return advapi32, kernel32


def _raise_windows_error(message: str, error: int | None = None) -> None:
    raise OSError(error or ctypes.get_last_error(), message)


def _current_windows_user_sid() -> str:
    advapi32, kernel32 = _windows_libraries()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        _TOKEN_QUERY,
        ctypes.byref(token),
    ):
        _raise_windows_error("Could not open the PostgreSQL test identity token.")
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        if not size.value:
            _raise_windows_error("Could not size the PostgreSQL test identity token.")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_USER,
            buffer,
            size,
            ctypes.byref(size),
        ):
            _raise_windows_error("Could not read the PostgreSQL test identity token.")
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        sid_pointer = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            token_user.user.sid,
            ctypes.byref(sid_pointer),
        ):
            _raise_windows_error("Could not render the PostgreSQL test identity SID.")
        try:
            return sid_pointer.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_pointer, wintypes.LPVOID))
    finally:
        kernel32.CloseHandle(token)


def _protected_sddl() -> str:
    sid = _current_windows_user_sid()
    return f"O:{sid}G:{sid}D:P(A;;FA;;;{sid})(A;;FA;;;SY)(A;;FA;;;BA)"


def _security_descriptor_from_sddl(sddl: str) -> tuple[ctypes.WinDLL, wintypes.LPVOID]:
    advapi32, kernel32 = _windows_libraries()
    descriptor = wintypes.LPVOID()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        _SDDL_REVISION_1,
        ctypes.byref(descriptor),
        None,
    ):
        _raise_windows_error("Could not build a protected PostgreSQL test file ACL.")
    return kernel32, descriptor


def _write_windows_protected_file(path: Path, content: str) -> None:
    import msvcrt

    _, kernel32 = _windows_libraries()
    descriptor_owner, descriptor = _security_descriptor_from_sddl(_protected_sddl())
    attributes = _SecurityAttributes(
        length=ctypes.sizeof(_SecurityAttributes),
        security_descriptor=descriptor,
        inherit_handle=False,
    )
    invalid_handle = wintypes.HANDLE(-1).value
    try:
        handle = kernel32.CreateFileW(
            str(path),
            _GENERIC_WRITE,
            0,
            ctypes.byref(attributes),
            _CREATE_NEW,
            _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_WRITE_THROUGH,
            None,
        )
        if handle == invalid_handle:
            _raise_windows_error("Could not create a protected PostgreSQL test file.")
        try:
            descriptor_number = msvcrt.open_osfhandle(
                int(handle),
                os.O_WRONLY | os.O_BINARY,
            )
        except OSError:
            kernel32.CloseHandle(handle)
            raise
        with os.fdopen(descriptor_number, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        descriptor_owner.LocalFree(descriptor)


def _windows_security_sddl(path: Path) -> str:
    advapi32, kernel32 = _windows_libraries()
    descriptor = wintypes.LPVOID()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        None,
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result:
        _raise_windows_error("Could not read a protected PostgreSQL test file ACL.", result)
    rendered = wintypes.LPWSTR()
    try:
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            _SDDL_REVISION_1,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(rendered),
            None,
        ):
            _raise_windows_error("Could not render a protected PostgreSQL test file ACL.")
        return rendered.value
    finally:
        if rendered:
            kernel32.LocalFree(ctypes.cast(rendered, wintypes.LPVOID))
        kernel32.LocalFree(descriptor)


def _assert_windows_acl(path: Path, *, label: str) -> None:
    sid = _current_windows_user_sid()
    sddl = _windows_security_sddl(path)
    owner_prefix = f"O:{sid}D:P"
    if not sddl.startswith(owner_prefix):
        raise RuntimeError(f"{label} owner or protected-DACL contract is invalid: {path}")
    rules = sddl.removeprefix(owner_prefix)
    expected = {
        f"(A;;FA;;;{sid})",
        "(A;;FA;;;SY)",
        "(A;;FA;;;BA)",
    }
    actual = {rule + ")" for rule in rules.split(")") if rule}
    if actual != expected or rules.count("(") != len(expected):
        raise RuntimeError(f"{label} ACL entries are invalid: {path}")


def assert_protected_authority_file(path: Path, *, label: str) -> Path:
    """Require one regular authority file with the platform protection contract."""

    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{label} is missing or not a regular absolute file: {path}")
    from scripts.test_pg_windows_contract import _assert_no_reparse_ancestors

    _assert_no_reparse_ancestors(path)
    if os.name == "nt":
        _assert_windows_acl(path, label=label)
    else:
        metadata = path.stat()
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError(f"{label} permissions must forbid group and other access: {path}")
        getuid = getattr(os, "geteuid", None)
        if getuid is not None and metadata.st_uid != getuid():
            raise RuntimeError(f"{label} is not owned by the current test identity: {path}")
    return path.resolve()


def write_protected_utf8_file(path: Path, content: str, *, label: str) -> Path:
    """Create one protected UTF-8 file with CREATE_NEW and durable contents."""

    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError(f"{label} parent directory is invalid: {path}")
    from scripts.test_pg_windows_contract import _assert_no_reparse_ancestors

    _assert_no_reparse_ancestors(path.parent)
    completed = False
    try:
        if os.name == "nt":
            _write_windows_protected_file(path, content)
        else:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        completed = True
    finally:
        if not completed:
            path.unlink(missing_ok=True)
    return assert_protected_authority_file(path, label=label)
