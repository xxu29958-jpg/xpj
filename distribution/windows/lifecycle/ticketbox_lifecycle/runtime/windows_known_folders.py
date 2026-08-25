from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from uuid import UUID

from ticketbox_lifecycle.errors import LifecycleViolation

_FOLDERID_PROGRAM_FILES = UUID("905e63b6-c1bf-494e-b29c-65b732d3d21a")
_FOLDERID_PROGRAM_FILES_COMMON_X64 = UUID("6365d5a7-0f0d-45e5-87f6-0da56b6a4f7d")


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


def ticketbox_install_root() -> Path:
    return _known_folder(
        _FOLDERID_PROGRAM_FILES,
        code="program_files_unavailable",
        label="Program Files",
    ) / "Ticketbox"


def ticketbox_control_root() -> Path:
    return _known_folder(
        _FOLDERID_PROGRAM_FILES_COMMON_X64,
        code="common_files_unavailable",
        label="Common Files x64",
    ) / "Ticketbox"


def _known_folder(folder_uuid: UUID, *, code: str, label: str) -> Path:
    if os.name != "nt":
        raise LifecycleViolation("windows_required", f"{label} requires Windows")
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
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    try:
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(path)
        )
        if result != 0 or not path.value:
            raise LifecycleViolation(
                code,
                f"cannot resolve the Windows {label} known folder "
                f"(HRESULT=0x{result & 0xFFFFFFFF:08x})",
            )
        return Path(path.value)
    finally:
        if path:
            ole32.CoTaskMemFree(ctypes.cast(path, ctypes.c_void_p))
