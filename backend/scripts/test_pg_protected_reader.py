"""Pinned reads for protected PostgreSQL authority files."""

from __future__ import annotations

import ctypes
import os
import stat
from ctypes import wintypes
from pathlib import Path

from scripts.test_pg_protected_file import (
    _FILE_SHARE_READ,
    _FILE_SHARE_WRITE,
    _GENERIC_READ,
    _assert_windows_acl,
    _raise_windows_error,
    _windows_libraries,
)

_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = (
        ("file_attributes", wintypes.DWORD),
        ("creation_time", wintypes.FILETIME),
        ("last_access_time", wintypes.FILETIME),
        ("last_write_time", wintypes.FILETIME),
        ("volume_serial_number", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("number_of_links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    )


def _open_windows_protected_read_descriptor(path: Path, *, label: str) -> int:
    import msvcrt

    _, kernel32 = _windows_libraries()
    kernel32.GetFileInformationByHandle.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    invalid_handle = wintypes.HANDLE(-1).value
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == invalid_handle:
        _raise_windows_error(f"Could not open {label}.")
    try:
        information = _ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(
            handle,
            ctypes.byref(information),
        ):
            _raise_windows_error(f"Could not identify {label}.")
        if information.file_attributes & (
            _FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise RuntimeError(f"{label} must be a regular non-reparse file: {path}")
        return msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except (OSError, RuntimeError):
        kernel32.CloseHandle(handle)
        raise


def read_protected_utf8_file(path: Path, *, label: str) -> str:
    """Read one protected authority file through the same pinned file object."""

    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError(f"{label} parent directory is invalid: {path}")
    from scripts.test_pg_windows_path_contract import _assert_no_reparse_ancestors

    _assert_no_reparse_ancestors(path.parent)
    if os.name == "nt":
        descriptor = _open_windows_protected_read_descriptor(path, label=label)
        try:
            _assert_windows_acl(path, label=label)
            with os.fdopen(
                descriptor,
                "r",
                encoding="utf-8",
                errors="strict",
                newline="",
            ) as stream:
                descriptor = -1
                return stream.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"{label} must be a regular file: {path}")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError(
                f"{label} permissions must forbid group and other access: {path}"
            )
        getuid = getattr(os, "geteuid", None)
        if getuid is not None and metadata.st_uid != getuid():
            raise RuntimeError(f"{label} is not owned by the current test identity: {path}")
        with os.fdopen(
            descriptor,
            "r",
            encoding="utf-8",
            errors="strict",
            newline="",
        ) as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
