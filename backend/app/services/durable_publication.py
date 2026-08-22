"""Crash-durable publication primitives for already-validated artifacts."""

from __future__ import annotations

import ctypes
import os
import stat
from pathlib import Path

from app.services.path_entry_safety import is_link_or_reparse

_MOVEFILE_REPLACE_EXISTING = 0x00000001
_MOVEFILE_WRITE_THROUGH = 0x00000008


def publish_durable_tree(staging: Path, target: Path) -> None:
    """Flush a plain staged tree and publish it to an absent same-parent target."""

    source, destination = _same_parent_paths(staging, target)
    if destination.exists() or not source.is_dir() or is_link_or_reparse(source):
        raise OSError("durable tree publication requires a plain tree and absent target")
    entries = tuple(source.rglob("*"))
    if any(is_link_or_reparse(item) for item in entries):
        raise OSError("durable tree publication rejects links and reparse points")
    files = tuple(item for item in entries if item.is_file())
    directories = tuple(item for item in entries if item.is_dir())
    if len(files) + len(directories) != len(entries):
        raise OSError("durable tree publication accepts only files and directories")
    for path in files:
        _flush_regular_file(path)
    source_identity = _identity(source)
    if os.name == "nt":
        _move_windows(source, destination, replace=False)
    else:
        for directory in sorted((*directories, source), key=lambda item: len(item.parts), reverse=True):
            _flush_unix_directory(directory)
        os.rename(source, destination)
        _flush_unix_directory(destination.parent)
    _assert_moved(source, destination, expected_identity=source_identity)


def replace_durable_file(staging: Path, target: Path) -> None:
    """Publish an already-flushed regular file and make the directory entry durable."""

    source, destination = _same_parent_paths(staging, target)
    if not source.is_file() or is_link_or_reparse(source):
        raise OSError("durable file publication requires a plain staging file")
    if is_link_or_reparse(destination) or (
        destination.exists() and not destination.is_file()
    ):
        raise OSError("durable file replacement target is not a plain file")
    source_identity = _identity(source)
    if os.name == "nt":
        _move_windows(source, destination, replace=True)
    else:
        os.replace(source, destination)
        _flush_unix_directory(destination.parent)
    _assert_moved(source, destination, expected_identity=source_identity)


def _same_parent_paths(staging: Path, target: Path) -> tuple[Path, Path]:
    source = Path(os.path.abspath(staging))
    destination = Path(os.path.abspath(target))
    if not staging.is_absolute() or not target.is_absolute() or source.parent != destination.parent:
        raise ValueError("durable publication requires absolute same-parent paths")
    return source, destination


def _flush_regular_file(path: Path) -> None:
    flags = os.O_RDWR if os.name == "nt" else os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("durable flush target is not a regular file")
        visible = path.stat(follow_symlinks=False)
        if (visible.st_dev, visible.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise OSError("durable flush target changed while opening")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _move_windows(source: Path, destination: Path, *, replace: bool) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.MoveFileExW.restype = ctypes.c_int
    flags = _MOVEFILE_WRITE_THROUGH | (_MOVEFILE_REPLACE_EXISTING if replace else 0)
    if not kernel32.MoveFileExW(str(source), str(destination), flags):
        raise ctypes.WinError(ctypes.get_last_error())


def _flush_unix_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _identity(path: Path) -> tuple[int, int]:
    metadata = path.stat(follow_symlinks=False)
    return int(metadata.st_dev), int(metadata.st_ino)


def _assert_moved(
    source: Path,
    destination: Path,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    if source.exists() or not destination.exists():
        raise OSError("durable publication did not move the staged artifact")
    if expected_identity is not None and _identity(destination) != expected_identity:
        raise OSError("durable publication changed artifact identity")
