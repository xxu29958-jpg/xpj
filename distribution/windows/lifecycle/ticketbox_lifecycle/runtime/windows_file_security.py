from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok

_FILE_DACL_BASE_SDDL = "D:PAI(A;;FA;;;SY)(A;;FA;;;BA)"
_DACL_INFORMATION = 0x00000004
_PROTECTED_DACL_INFORMATION = 0x80000000
_SE_FILE_OBJECT = 1
_SDDL_REVISION_1 = 1


class FileSecurity(Protocol):
    def protect_file(
        self,
        runner: CommandRunner,
        path: Path,
        *,
        reader_sids: tuple[str, ...],
        code: str,
    ) -> None: ...


class WindowsFileSecurity:
    def protect_file(
        self,
        runner: CommandRunner,
        path: Path,
        *,
        reader_sids: tuple[str, ...],
        code: str,
    ) -> None:
        native.reject_reparse_components(path)
        if not path.is_file():
            raise LifecycleViolation("credential_invalid", f"not a regular file: {path.name}")
        require_ok(runner.run(["takeown", "/A", "/F", str(path)]), code=f"{code}_owner")
        _apply_file_dacl(path, reader_sids, code=code)


def file_dacl_sddl(reader_sids: tuple[str, ...]) -> str:
    if any(native._SID_PATTERN.fullmatch(sid) is None for sid in reader_sids):
        raise LifecycleViolation("file_reader_sid_invalid", "file reader SID is not canonical")
    return _FILE_DACL_BASE_SDDL + "".join(f"(A;;FR;;;{sid})" for sid in reader_sids)

def _apply_file_dacl(path: Path, reader_sids: tuple[str, ...], *, code: str) -> None:
    import ctypes
    from ctypes import wintypes

    native.require_windows()
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    local_free = kernel.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    get_dacl.restype = wintypes.BOOL
    set_named = advapi.SetNamedSecurityInfoW
    set_named.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    set_named.restype = wintypes.DWORD
    descriptor = ctypes.c_void_p()
    if not convert(
        file_dacl_sddl(reader_sids),
        _SDDL_REVISION_1,
        ctypes.byref(descriptor),
        None,
    ):
        raise LifecycleError(code, f"cannot build the file DACL: {ctypes.get_last_error()}")
    try:
        present = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        defaulted = wintypes.BOOL()
        if not get_dacl(
            descriptor,
            ctypes.byref(present),
            ctypes.byref(dacl),
            ctypes.byref(defaulted),
        ) or not present.value or not dacl.value:
            raise LifecycleError(code, "converted file security descriptor has no DACL")
        result = set_named(
            str(path),
            _SE_FILE_OBJECT,
            _DACL_INFORMATION | _PROTECTED_DACL_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
        if result != 0:
            raise LifecycleError(code, f"SetNamedSecurityInfoW failed for {path.name}: {result}")
    finally:
        local_free(descriptor)
