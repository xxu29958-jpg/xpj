"""Atomic protected-file helpers for PostgreSQL test authority material."""

from __future__ import annotations

import ctypes
import os
import stat
from ctypes import wintypes
from pathlib import Path

from scripts.test_pg_windows_acl import (
    ACCESS_ALLOWED_ACE_TYPE,
    CONTAINER_INHERIT_ACE,
    FILE_ALL_ACCESS,
    OBJECT_INHERIT_ACE,
    SDDL_REVISION_1,
    SecurityAttributes,
    current_windows_user_sid,
    raise_windows_error,
    windows_libraries,
    windows_security_parts,
)

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_CREATE_NEW = 1
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_WRITE_THROUGH = 0x80000000


def _protected_sddl(*, directory: bool = False) -> str:
    sid = current_windows_user_sid()
    inheritance = "OICI" if directory else ""
    return (
        f"O:{sid}G:{sid}D:P"
        f"(A;{inheritance};FA;;;{sid})"
        f"(A;{inheritance};FA;;;SY)"
        f"(A;{inheritance};FA;;;BA)"
    )


def _security_descriptor_from_sddl(sddl: str) -> tuple[ctypes.WinDLL, wintypes.LPVOID]:
    advapi32, kernel32 = windows_libraries()
    descriptor = wintypes.LPVOID()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        SDDL_REVISION_1,
        ctypes.byref(descriptor),
        None,
    ):
        raise_windows_error("Could not build a protected PostgreSQL test file ACL.")
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

    _, kernel32 = windows_libraries()
    descriptor_owner, descriptor = _security_descriptor_from_sddl(_protected_sddl())
    attributes = SecurityAttributes(
        length=ctypes.sizeof(SecurityAttributes),
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
            raise_windows_error(f"Could not create {label}.")
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


def _assert_windows_acl(path: Path, *, label: str) -> None:
    sid = current_windows_user_sid()
    actual_owner, protected, entries = windows_security_parts(path)
    if actual_owner != sid or not protected:
        raise RuntimeError(
            f"{label} owner or protected-DACL contract is invalid: "
            f"{path} owner={actual_owner} protected={protected}"
        )
    expected_sids = {sid, "S-1-5-18", "S-1-5-32-544"}
    expected_flags = (
        OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE if path.is_dir() else 0
    )
    actual_sids = {entry[0] for entry in entries}
    entries_are_exact = all(
        mask == FILE_ALL_ACCESS
        and flags == expected_flags
        and ace_type == ACCESS_ALLOWED_ACE_TYPE
        for _, mask, flags, ace_type in entries
    )
    if (
        len(entries) != len(expected_sids)
        or actual_sids != expected_sids
        or not entries_are_exact
    ):
        raise RuntimeError(f"{label} ACL entries are invalid: {path} entries={entries!r}")


def ensure_protected_directory(path: Path, *, label: str) -> Path:
    """Create or validate one protected directory with trusted inheritable ACLs."""

    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError(f"{label} parent directory is invalid: {path}")
    from scripts.test_pg_windows_path_contract import _assert_no_reparse_ancestors

    _assert_no_reparse_ancestors(path.parent)
    created = False
    if os.name == "nt":
        _, kernel32 = windows_libraries()
        descriptor_owner, descriptor = _security_descriptor_from_sddl(
            _protected_sddl(directory=True)
        )
        attributes = SecurityAttributes(
            length=ctypes.sizeof(SecurityAttributes),
            security_descriptor=descriptor,
            inherit_handle=False,
        )
        try:
            if kernel32.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                created = True
            else:
                error = ctypes.get_last_error()
                if error != 183:
                    raise_windows_error(f"Could not create {label}.", error)
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
