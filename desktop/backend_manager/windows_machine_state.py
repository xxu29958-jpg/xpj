"""Resolve and read the one protected Windows installed-instance binding."""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from pathlib import Path
from uuid import UUID

from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_trusted_file import (
    file_security_descriptor,
    lookup_account_sid,
    open_exclusive_file,
    reject_reparse_components,
)
from backend_manager.windows_user_security import current_user_sid

_FOLDERID_PROGRAM_DATA = UUID("62ab5d82-fdc1-4dc3-a9dd-070d1d495d97")
_BACKEND_SERVICE_ACCOUNT = r"NT SERVICE\TicketboxBackend"
_ADMINISTRATORS_SID = "S-1-5-32-544"
_SYSTEM_SID = "S-1-5-18"
_MAX_BINDING_BYTES = 64 * 1024
_ACE_PATTERN = re.compile(r"\(([^()]*)\)")


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


def program_data_root() -> Path:
    if os.name != "nt":
        raise RuntimeControlError("Windows 安装绑定只支持 Windows。")
    folder_id = _GUID.from_uuid(_FOLDERID_PROGRAM_DATA)
    value = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("Shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("Ole32", use_last_error=True)
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
            ctypes.byref(folder_id),
            0,
            None,
            ctypes.byref(value),
        )
        if result != 0 or not value.value:
            raise RuntimeControlError(
                f"无法定位 Windows ProgramData（HRESULT=0x{result & 0xFFFFFFFF:08x}）。"
            )
        return Path(value.value)
    finally:
        if value:
            ole32.CoTaskMemFree(ctypes.cast(value, ctypes.c_void_p))


def machine_binding_path() -> Path:
    return program_data_root() / "Ticketbox" / "machine" / "installation.json"


def read_protected_binding_bytes() -> bytes | None:
    path = machine_binding_path()
    reject_reparse_components(path)
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeControlError("无法检查 installation.json。") from exc
    user_sid = current_user_sid()
    backend_sid = lookup_account_sid(_BACKEND_SERVICE_ACCOUNT)
    with open_exclusive_file(path, writable=False) as stream:
        _require_path_security(path, user_sid=user_sid, backend_sid=backend_sid)
        payload = stream.read(_MAX_BINDING_BYTES + 1)
        _require_path_security(path, user_sid=user_sid, backend_sid=backend_sid)
    if len(payload) > _MAX_BINDING_BYTES:
        raise RuntimeControlError("installation.json 超出大小上限。")
    return payload


def _require_path_security(path: Path, *, user_sid: str, backend_sid: str) -> None:
    owner, sddl = file_security_descriptor(path)
    _require_exact_binding_security(
        owner,
        sddl,
        current_user_sid=user_sid,
        backend_service_sid=backend_sid,
    )


def _require_exact_binding_security(
    owner_sid: str,
    sddl: str,
    *,
    current_user_sid: str,
    backend_service_sid: str,
) -> None:
    if owner_sid.casefold() not in {
        _ADMINISTRATORS_SID.casefold(),
        _SYSTEM_SID.casefold(),
    }:
        raise RuntimeControlError("installation.json owner 不受信任。")
    dacl = sddl.partition("D:")[2]
    if not dacl.startswith("P"):
        raise RuntimeControlError("installation.json DACL 未禁止继承。")
    expected = {
        "SY": "FA",
        "BA": "FA",
        backend_service_sid.upper(): "FR",
        current_user_sid.upper(): "FR",
    }
    observed: dict[str, str] = {}
    aces = _ACE_PATTERN.findall(dacl)
    if len(aces) != len(expected):
        raise RuntimeControlError("installation.json DACL 包含额外或缺失主体。")
    for raw in aces:
        fields = raw.split(";")
        if len(fields) != 6 or fields[0] != "A" or fields[1] != "":
            raise RuntimeControlError("installation.json DACL 规则不精确。")
        principal = fields[5].upper()
        principal = {
            _SYSTEM_SID: "SY",
            _ADMINISTRATORS_SID: "BA",
        }.get(principal, principal)
        if principal in observed or expected.get(principal) != fields[2]:
            raise RuntimeControlError("installation.json DACL 权限不精确。")
        observed[principal] = fields[2]
    if observed != expected:
        raise RuntimeControlError("installation.json DACL 不完整。")
