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
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_CREATE_NEW = 1
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_WRITE_THROUGH = 0x80000000
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_TOKEN_OWNER = 4


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


class _TokenOwner(ctypes.Structure):
    _fields_ = (("owner", wintypes.LPVOID),)


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
    kernel32.CreateDirectoryW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.POINTER(_SecurityAttributes),
    )
    kernel32.CreateDirectoryW.restype = wintypes.BOOL
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


@cache
def _current_windows_token_sid(information_class: int) -> str:
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
        advapi32.GetTokenInformation(token, information_class, None, 0, ctypes.byref(size))
        if not size.value:
            _raise_windows_error("Could not size the PostgreSQL test identity token.")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token,
            information_class,
            buffer,
            size,
            ctypes.byref(size),
        ):
            _raise_windows_error("Could not read the PostgreSQL test identity token.")
        if information_class == _TOKEN_USER:
            sid = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents.user.sid
        elif information_class == _TOKEN_OWNER:
            sid = ctypes.cast(buffer, ctypes.POINTER(_TokenOwner)).contents.owner
        else:
            raise ValueError(f"Unsupported Windows token SID class: {information_class}")
        sid_pointer = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            sid,
            ctypes.byref(sid_pointer),
        ):
            _raise_windows_error("Could not render the PostgreSQL test identity SID.")
        try:
            return sid_pointer.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_pointer, wintypes.LPVOID))
    finally:
        kernel32.CloseHandle(token)


def _current_windows_user_sid() -> str:
    return _current_windows_token_sid(_TOKEN_USER)


def _current_windows_owner_sid() -> str:
    return _current_windows_token_sid(_TOKEN_OWNER)


def _protected_sddl(*, directory: bool = False) -> str:
    sid = _current_windows_user_sid()
    owner_sid = _current_windows_owner_sid()
    inheritance = "OICI" if directory else ""
    return (
        f"O:{owner_sid}G:{owner_sid}D:P"
        f"(A;{inheritance};FA;;;{sid})"
        f"(A;{inheritance};FA;;;SY)"
        f"(A;{inheritance};FA;;;BA)"
    )


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


def _create_windows_protected_file_descriptor(
    path: Path,
    *,
    desired_access: int,
    share_mode: int,
    os_flags: int,
    label: str,
) -> int:
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
            desired_access,
            share_mode,
            ctypes.byref(attributes),
            _CREATE_NEW,
            _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_WRITE_THROUGH,
            None,
        )
        if handle == invalid_handle:
            _raise_windows_error(f"Could not create {label}.")
        try:
            return msvcrt.open_osfhandle(
                int(handle),
                os_flags,
            )
        except OSError:
            kernel32.CloseHandle(handle)
            raise
    finally:
        descriptor_owner.LocalFree(descriptor)


def _write_windows_protected_file(path: Path, content: str) -> None:
    descriptor_number = _create_windows_protected_file_descriptor(
        path,
        desired_access=_GENERIC_WRITE,
        share_mode=0,
        os_flags=os.O_WRONLY | os.O_BINARY,
        label="a protected PostgreSQL test file",
    )
    completed = False
    try:
        with os.fdopen(descriptor_number, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        completed = True
    finally:
        if not completed:
            path.unlink(missing_ok=True)


def create_protected_shared_lock_file(path: Path, *, label: str) -> int:
    """Create one empty protected shared lock file and return its descriptor."""

    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError(f"{label} parent directory is invalid: {path}")
    from scripts.test_pg_windows_path_contract import _assert_no_reparse_ancestors

    _assert_no_reparse_ancestors(path.parent)
    if os.name == "nt":
        descriptor = _create_windows_protected_file_descriptor(
            path,
            desired_access=_GENERIC_READ | _GENERIC_WRITE,
            share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            os_flags=os.O_RDWR | os.O_BINARY,
            label=label,
        )
    else:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    completed = False
    try:
        assert_protected_authority_file(path, label=label)
        completed = True
        return descriptor
    finally:
        if not completed:
            os.close(descriptor)
            path.unlink(missing_ok=True)


def _windows_security_parts(path: Path) -> tuple[str, str]:
    advapi32, kernel32 = _windows_libraries()
    descriptor = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    result = advapi32.GetNamedSecurityInfoW(
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
        _raise_windows_error("Could not read a protected PostgreSQL test file ACL.", result)
    rendered = wintypes.LPWSTR()
    rendered_owner = wintypes.LPWSTR()
    try:
        if not advapi32.ConvertSidToStringSidW(owner, ctypes.byref(rendered_owner)):
            _raise_windows_error("Could not render a protected PostgreSQL test file owner.")
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor,
            _SDDL_REVISION_1,
            _DACL_SECURITY_INFORMATION,
            ctypes.byref(rendered),
            None,
        ):
            _raise_windows_error("Could not render a protected PostgreSQL test file ACL.")
        return rendered_owner.value, rendered.value
    finally:
        if rendered_owner:
            kernel32.LocalFree(ctypes.cast(rendered_owner, wintypes.LPVOID))
        if rendered:
            kernel32.LocalFree(ctypes.cast(rendered, wintypes.LPVOID))
        kernel32.LocalFree(descriptor)


def _assert_windows_acl(path: Path, *, label: str) -> None:
    sid = _current_windows_user_sid()
    expected_owner_sid = _current_windows_owner_sid()
    actual_owner_sid, sddl = _windows_security_parts(path)
    if actual_owner_sid != expected_owner_sid or not sddl.startswith("D:"):
        raise RuntimeError(f"{label} owner or protected-DACL contract is invalid: {path}")
    rules_start = sddl.find("(")
    flags = sddl[2:rules_start] if rules_start >= 0 else sddl[2:]
    unsupported_flags = flags.replace("AR", "").replace("AI", "").replace("P", "")
    if "P" not in flags or unsupported_flags:
        raise RuntimeError(f"{label} owner or protected-DACL contract is invalid: {path}")
    rules = sddl[rules_start:] if rules_start >= 0 else ""
    inheritance = "OICI" if path.is_dir() else ""
    expected = {
        f"(A;{inheritance};FA;;;{sid})",
        f"(A;{inheritance};FA;;;SY)",
        f"(A;{inheritance};FA;;;BA)",
    }
    actual = {rule + ")" for rule in rules.split(")") if rule}
    if actual != expected or rules.count("(") != len(expected):
        raise RuntimeError(f"{label} ACL entries are invalid: {path}")


def ensure_protected_directory(path: Path, *, label: str) -> Path:
    """Create or validate one protected directory with trusted inheritable ACLs."""

    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError(f"{label} parent directory is invalid: {path}")
    from scripts.test_pg_windows_path_contract import _assert_no_reparse_ancestors

    _assert_no_reparse_ancestors(path.parent)
    created = False
    if os.name == "nt":
        _, kernel32 = _windows_libraries()
        descriptor_owner, descriptor = _security_descriptor_from_sddl(
            _protected_sddl(directory=True)
        )
        attributes = _SecurityAttributes(
            length=ctypes.sizeof(_SecurityAttributes),
            security_descriptor=descriptor,
            inherit_handle=False,
        )
        try:
            if kernel32.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                created = True
            else:
                error = ctypes.get_last_error()
                if error != 183:
                    _raise_windows_error(f"Could not create {label}.", error)
        finally:
            descriptor_owner.LocalFree(descriptor)
    else:
        try:
            path.mkdir(mode=0o700)
            created = True
        except FileExistsError:
            pass
    try:
        if not path.is_dir() or path.is_symlink():
            raise RuntimeError(f"{label} is not a regular directory: {path}")
        _assert_no_reparse_ancestors(path)
        if os.name == "nt":
            _assert_windows_acl(path, label=label)
        elif stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise RuntimeError(f"{label} permissions are too broad: {path}")
        return path.resolve()
    except (OSError, RuntimeError):
        if created:
            path.rmdir()
        raise


def assert_protected_authority_file(path: Path, *, label: str) -> Path:
    """Require one regular authority file with the platform protection contract."""

    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{label} is missing or not a regular absolute file: {path}")
    from scripts.test_pg_windows_path_contract import _assert_no_reparse_ancestors

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
    from scripts.test_pg_windows_path_contract import _assert_no_reparse_ancestors

    _assert_no_reparse_ancestors(path.parent)
    created = False
    completed = False
    try:
        if os.name == "nt":
            _write_windows_protected_file(path, content)
            created = True
        else:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        completed = True
    finally:
        if created and not completed:
            path.unlink(missing_ok=True)
    return assert_protected_authority_file(path, label=label)
