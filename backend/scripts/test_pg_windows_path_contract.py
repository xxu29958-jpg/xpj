"""No-follow Windows path leases for PostgreSQL test authority roots."""

from __future__ import annotations

import contextlib
import ctypes
import os
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
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
    ]


def _windows_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & 0x400)


def _assert_no_reparse_ancestors(path: Path) -> None:
    if os.name != "nt":
        return
    current = path
    while True:
        if _windows_reparse_point(current):
            raise RuntimeError(
                f"Test PostgreSQL authority path must not be a reparse point: {current}"
            )
        if current.parent == current:
            return
        current = current.parent


def _lexical_absolute_path(path: Path, *, label: str) -> Path:
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be an absolute path: {path}")
    return Path(os.path.abspath(os.path.normpath(path)))


def _path_kernel32() -> object:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _open_directory_component(kernel32: object, path: Path) -> object:
    handle = kernel32.CreateFileW(
        str(path),
        0x00000080,
        0x00000001 | 0x00000002,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(
            ctypes.get_last_error(),
            f"Cannot lease PostgreSQL path component: {path}",
        )
    information = _ByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(
        handle,
        ctypes.byref(information),
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise OSError(error, f"Cannot identify PostgreSQL path component: {path}")
    if (
        not information.file_attributes & 0x00000010
        or information.file_attributes & 0x00000400
    ):
        kernel32.CloseHandle(handle)
        raise RuntimeError(f"PostgreSQL path component must be a real directory: {path}")
    return handle


@contextlib.contextmanager
def _windows_directory_path_lease(path: Path) -> Iterator[None]:
    full_path = _lexical_absolute_path(
        path,
        label="PostgreSQL directory path lease",
    )
    root = Path(full_path.anchor)
    components = full_path.parts[1:]
    kernel32 = _path_kernel32()
    opened: list[object] = []
    try:
        current = root
        for component in (None, *components):
            if component is not None:
                current /= component
            opened.append(_open_directory_component(kernel32, current))
        yield
    finally:
        for handle in reversed(opened):
            kernel32.CloseHandle(handle)
