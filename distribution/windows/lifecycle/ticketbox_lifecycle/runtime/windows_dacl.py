from __future__ import annotations

from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_security_native as native

_DACL_INFORMATION = 0x00000004
_PROTECTED_DACL_INFORMATION = 0x80000000
_SE_FILE_OBJECT = 1
_SDDL_REVISION_1 = 1


def apply_protected_dacl(path: Path, dacl_sddl: str, *, code: str) -> None:
    import ctypes
    from ctypes import wintypes

    native.require_windows()
    native.reject_reparse_components(path)
    if not dacl_sddl.startswith("D:P"):
        raise LifecycleError(
            code, "DACL policy must protect the target from parent inheritance"
        )

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
        dacl_sddl,
        _SDDL_REVISION_1,
        ctypes.byref(descriptor),
        None,
    ):
        raise LifecycleError(
            code, f"cannot build the protected DACL: {ctypes.get_last_error()}"
        )
    try:
        present = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        defaulted = wintypes.BOOL()
        if (
            not get_dacl(
                descriptor,
                ctypes.byref(present),
                ctypes.byref(dacl),
                ctypes.byref(defaulted),
            )
            or not present.value
            or not dacl.value
        ):
            raise LifecycleError(code, "converted security descriptor has no DACL")
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
            raise LifecycleError(
                code, f"SetNamedSecurityInfoW failed for {path.name}: {result}"
            )
    finally:
        local_free(descriptor)
