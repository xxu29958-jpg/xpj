"""Stable single-handle reads for immutable maintenance inputs."""

from __future__ import annotations

import contextlib
import ctypes
import os
import stat
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path
from typing import BinaryIO

from app.services import secure_file_windows as _windows

_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("file_attributes", wintypes.DWORD),
        ("creation_time", _FileTime),
        ("last_access_time", _FileTime),
        ("last_write_time", _FileTime),
        ("volume_serial_number", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("number_of_links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    ]


def _require_single_link(kernel32: object, handle: wintypes.HANDLE) -> None:
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    info = _ByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if info.number_of_links != 1:
        raise OSError("stable file must have exactly one directory entry")


@contextlib.contextmanager
def _hold_windows_file(path: Path) -> Iterator[BinaryIO]:
    import msvcrt

    _advapi32, kernel32 = _windows.windows_apis()
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if not handle or handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = -1
    try:
        _windows.validate_file_identity(kernel32, handle, path)
        _require_single_link(kernel32, handle)
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            yield stream
            _require_single_link(kernel32, msvcrt.get_osfhandle(stream.fileno()))
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if handle:
            kernel32.CloseHandle(handle)


@contextlib.contextmanager
def _hold_unix_file(path: Path) -> Iterator[BinaryIO]:
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent = os.open(path.anchor, directory_flags)
    descriptor = -1
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.name, file_flags, dir_fd=parent)
        metadata = os.fstat(descriptor)
        visible = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (visible.st_dev, visible.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise OSError("stable file must be one visible single-link regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            yield stream
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)


@contextlib.contextmanager
def hold_stable_file_for_read(path: Path) -> Iterator[BinaryIO]:
    """Hold a no-reparse, single-link file while reading from that exact handle."""

    lexical = Path(os.path.abspath(path))
    if not path.is_absolute() or not lexical.anchor or not lexical.name:
        raise ValueError("stable file path must be an absolute file path")
    holder = _hold_windows_file if os.name == "nt" else _hold_unix_file
    with holder(lexical) as stream:
        yield stream
