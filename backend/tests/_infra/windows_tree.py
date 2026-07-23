"""Handle-bound deletion for Windows test runtime trees."""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from collections.abc import Callable, Iterator
from ctypes import wintypes
from pathlib import Path

_DELETE = 0x00010000
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_DISPOSITION_INFO_CLASS = 4
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = (("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD))


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = (("delete_file", wintypes.BOOL),)


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_CREATE_FILE = _KERNEL32.CreateFileW
_CREATE_FILE.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
_CREATE_FILE.restype = wintypes.HANDLE
_CLOSE_HANDLE = _KERNEL32.CloseHandle
_CLOSE_HANDLE.argtypes = (wintypes.HANDLE,)
_CLOSE_HANDLE.restype = wintypes.BOOL
_GET_FILE_INFORMATION = _KERNEL32.GetFileInformationByHandleEx
_GET_FILE_INFORMATION.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
)
_GET_FILE_INFORMATION.restype = wintypes.BOOL
_GET_FINAL_PATH = _KERNEL32.GetFinalPathNameByHandleW
_GET_FINAL_PATH.argtypes = (
    wintypes.HANDLE,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
)
_GET_FINAL_PATH.restype = wintypes.DWORD
_SET_FILE_INFORMATION = _KERNEL32.SetFileInformationByHandle
_SET_FILE_INFORMATION.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
)
_SET_FILE_INFORMATION.restype = wintypes.BOOL


def _win_error(operation: str, path: Path) -> OSError:
    error = ctypes.get_last_error()
    return ctypes.WinError(error, f"{operation}: {path}")


def _normalized(path: str | Path) -> str:
    value = os.path.abspath(os.fspath(path))
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.normpath(value))


@contextlib.contextmanager
def _open_exact(path: Path) -> Iterator[int]:
    handle = _CREATE_FILE(
        str(path),
        _DELETE | _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle in {None, _INVALID_HANDLE_VALUE}:
        raise _win_error("unable to open exact deletion target", path)
    try:
        yield handle
    finally:
        if not _CLOSE_HANDLE(handle) and sys.exc_info()[0] is None:
            raise _win_error("unable to close exact deletion target", path)


def _attributes(handle: int, path: Path) -> int:
    info = _FileAttributeTagInfo()
    if not _GET_FILE_INFORMATION(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _win_error("unable to inspect exact deletion target", path)
    return int(info.attributes)


def _verify_path(handle: int, expected: Path) -> None:
    capacity = 512
    while True:
        buffer = ctypes.create_unicode_buffer(capacity)
        length = _GET_FINAL_PATH(handle, buffer, capacity, 0)
        if length == 0:
            raise _win_error("unable to resolve exact deletion target", expected)
        if length < capacity:
            actual = buffer.value
            break
        capacity = int(length) + 1
    if _normalized(actual) != _normalized(expected):
        raise OSError(f"opened deletion target escaped its requested path: {expected} -> {actual}")


def _mark_deleted(handle: int, path: Path) -> None:
    disposition = _FileDispositionInfo(True)
    if not _SET_FILE_INFORMATION(
        handle,
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise _win_error("unable to delete exact opened path", path)


def _delete_opened(path: Path, handle: int) -> None:
    attributes = _attributes(handle, path)
    if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError(f"refusing to delete a test runtime reparse point: {path}")
    if attributes & _FILE_ATTRIBUTE_DIRECTORY:
        with os.scandir(path) as entries:
            children = tuple(entry.name for entry in entries)
        for name in children:
            child = path / name
            with _open_exact(child) as child_handle:
                _verify_path(child_handle, child)
                _delete_opened(child, child_handle)
    _mark_deleted(handle, path)


def remove_tree_exact(
    path: Path,
    *,
    on_root_opened: Callable[[Path], None] | None = None,
) -> None:
    """Delete the exact non-reparse tree opened at ``path``."""
    if os.name != "nt":
        raise RuntimeError("Windows exact tree deletion is only available on Windows")
    target = Path(os.path.abspath(path))
    if not os.path.lexists(target):
        return
    with _open_exact(target) as root:
        _verify_path(root, target)
        if on_root_opened is not None:
            on_root_opened(target)
        _delete_opened(target, root)
    if os.path.lexists(target):
        raise OSError(f"test runtime still exists after exact deletion: {target}")
