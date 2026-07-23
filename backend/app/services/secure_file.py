"""Creation-time protection for short-lived secret files."""

from __future__ import annotations

import contextlib
import ctypes
import os
import stat
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path

_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
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


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("user", _SidAndAttributes)]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("security_descriptor", ctypes.c_void_p),
        ("inherit_handle", wintypes.BOOL),
    ]


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]


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


def _validate_unix_directory_entry(
    directory: os.stat_result,
    *,
    child_owner: int,
) -> None:
    if not stat.S_ISDIR(directory.st_mode):
        raise ValueError("protected file parent chain contains a non-directory")
    effective_uid = os.geteuid()
    if directory.st_uid not in {0, effective_uid}:
        raise PermissionError("protected file parent directory has an untrusted owner")
    if directory.st_mode & 0o022 and (
        not directory.st_mode & stat.S_ISVTX or child_owner != effective_uid
    ):
        raise PermissionError("protected file parent directory is mutable by another user")


@contextlib.contextmanager
def _open_unix_parent(path: Path) -> Iterator[tuple[int, os.stat_result, str]]:
    lexical = Path(os.path.abspath(path))
    if not path.is_absolute() or not lexical.anchor or not lexical.name:
        raise ValueError("protected file path must be an absolute file path")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lexical.anchor, flags)
    try:
        current = os.fstat(descriptor)
        for component in lexical.parts[1:-1]:
            child_descriptor = os.open(component, flags, dir_fd=descriptor)
            try:
                child = os.fstat(child_descriptor)
                _validate_unix_directory_entry(current, child_owner=child.st_uid)
            except (OSError, ValueError):
                os.close(child_descriptor)
                raise
            os.close(descriptor)
            descriptor = child_descriptor
            current = child
        yield descriptor, current, lexical.name
    finally:
        os.close(descriptor)


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


def _windows_apis() -> tuple[object, object]:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_advapi32(advapi32)
    _configure_kernel32(kernel32)
    return advapi32, kernel32


def _current_process_sid(advapi32: object, kernel32: object) -> str:
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


def _protected_security_descriptor(advapi32: object, sid: str) -> ctypes.c_void_p:
    descriptor = ctypes.c_void_p()
    sddl = f"O:{sid}D:P(A;;FA;;;{sid})(A;;FA;;;SY)(A;;FA;;;BA)"
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


def _validate_windows_file_identity(
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


def _validate_windows_file_acl(
    advapi32: object,
    kernel32: object,
    handle: wintypes.HANDLE,
) -> None:
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi32.GetSecurityInfo(
        handle,
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise ctypes.WinError(result)
    try:
        current_sid = _current_process_sid(advapi32, kernel32)
        if not owner or _sid_string(advapi32, kernel32, owner) != current_sid:
            raise PermissionError("protected file owner is not the current process user")
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(
            descriptor,
            ctypes.byref(control),
            ctypes.byref(revision),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not control.value & _SE_DACL_PROTECTED or not dacl:
            raise PermissionError("protected file DACL is inherited or missing")
        size = _AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(size),
            ctypes.sizeof(size),
            _ACL_SIZE_INFORMATION_CLASS,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        allowed_sids = {current_sid, "S-1-5-18", "S-1-5-32-544"}
        present_sids: set[str] = set()
        for index in range(size.ace_count):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                raise ctypes.WinError(ctypes.get_last_error())
            ace = ctypes.cast(ace_pointer, ctypes.POINTER(_AccessAllowedAce)).contents
            if (
                ace.header.ace_type != _ACCESS_ALLOWED_ACE_TYPE
                or ace.header.ace_flags & _INHERITED_ACE
                or ace.mask != _FILE_ALL_ACCESS
            ):
                raise PermissionError("protected file contains a non-exact access rule")
            sid_pointer = ctypes.c_void_p(
                ace_pointer.value + _AccessAllowedAce.sid_start.offset
            )
            sid = _sid_string(advapi32, kernel32, sid_pointer)
            if sid not in allowed_sids or sid in present_sids:
                raise PermissionError("protected file contains an unauthorized access rule")
            present_sids.add(sid)
        if current_sid not in present_sids:
            raise PermissionError("protected file DACL does not grant the current user")
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)


@contextlib.contextmanager
def _hold_windows_protected_file(path: Path) -> Iterator[Path]:
    advapi32, kernel32 = _windows_apis()
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
        resolved = _validate_windows_file_identity(kernel32, handle, path)
        _validate_windows_file_acl(advapi32, kernel32, handle)
        yield resolved
    finally:
        kernel32.CloseHandle(handle)


@contextlib.contextmanager
def hold_protected_file_for_read(path: Path) -> Iterator[Path]:
    """Hold a validated secret file so Windows cannot replace it during use."""
    if not path.is_absolute():
        raise ValueError("protected file path must be absolute")
    if os.name == "nt":
        with _hold_windows_protected_file(path) as resolved:
            yield resolved
        return

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    with _open_unix_parent(path) as (parent, parent_metadata, name):
        descriptor = os.open(name, flags, dir_fd=parent)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("protected file must be a regular non-symlink file")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise PermissionError("protected file permissions are too broad")
            if metadata.st_uid != os.geteuid():
                raise PermissionError("protected file owner does not match the current user")
            _validate_unix_directory_entry(parent_metadata, child_owner=metadata.st_uid)
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (visible.st_dev, visible.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise OSError("protected file changed while it was being opened")
            yield Path(os.path.abspath(path))
        finally:
            os.close(descriptor)


def _write_windows_file(
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


def _write_windows_protected_file(path: Path, payload: bytes) -> None:
    advapi32, kernel32 = _windows_apis()
    descriptor = _protected_security_descriptor(
        advapi32,
        _current_process_sid(advapi32, kernel32),
    )
    try:
        _write_windows_file(kernel32, path, payload, descriptor)
    finally:
        kernel32.LocalFree(descriptor)


def write_protected_file_exclusive(path: Path, text: str) -> None:
    """Create a new file whose secret is never visible under inherited ACLs."""
    payload = text.encode("utf-8")
    if os.name == "nt":
        _write_windows_protected_file(path, payload)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    with _open_unix_parent(path) as (parent, parent_metadata, name):
        _validate_unix_directory_entry(parent_metadata, child_owner=os.geteuid())
        descriptor = os.open(name, flags, 0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
