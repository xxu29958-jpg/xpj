"""One native Known Folder resolver; callers own product paths and error presentation."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from uuid import UUID

PROGRAM_DATA_FOLDER_ID = UUID("62ab5d82-fdc1-4dc3-a9dd-070d1d495d97")
DOWNLOADS_FOLDER_ID = UUID("374de290-123f-4565-9164-39c4925e467b")
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = 0x80010106


class KnownFolderError(OSError):
    def __init__(self, code: str, hresult: int | None = None) -> None:
        self.code = code
        self.hresult = None if hresult is None else hresult & 0xFFFFFFFF
        super().__init__(code)


class _GUID(ctypes.Structure):
    _fields_ = (
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def from_uuid(cls, value: UUID) -> _GUID:
        data1, data2, data3, data4_hi, data4_low, node = value.fields
        tail = bytes((data4_hi, data4_low)) + node.to_bytes(6, "big")
        return cls(data1, data2, data3, (ctypes.c_ubyte * 8)(*tail))


def known_folder_path(folder_uuid: UUID) -> Path:
    if os.name != "nt":
        raise KnownFolderError("windows_required")
    folder_id = _GUID.from_uuid(folder_uuid)
    path = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.SHGetKnownFolderPath.argtypes = (
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    )
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = ()
    ole32.CoUninitialize.restype = None
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    with _com_initialized(ole32):
        try:
            result = shell32.SHGetKnownFolderPath(
                ctypes.byref(folder_id), 0, None, ctypes.byref(path)
            )
            if result != 0 or not path.value:
                raise KnownFolderError("folder_unavailable", result)
            return Path(path.value)
        finally:
            if path:
                ole32.CoTaskMemFree(ctypes.cast(path, ctypes.c_void_p))


@contextmanager
def _com_initialized(ole32: object) -> Iterator[None]:
    result = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    normalized = result & 0xFFFFFFFF
    should_uninitialize = normalized in {0, 1}
    if not should_uninitialize and normalized != _RPC_E_CHANGED_MODE:
        raise KnownFolderError("com_initialization_failed", normalized)
    try:
        yield
    finally:
        if should_uninitialize:
            ole32.CoUninitialize()
