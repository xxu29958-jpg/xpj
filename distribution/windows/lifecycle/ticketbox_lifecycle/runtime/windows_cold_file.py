"""Create one private new archive handle before any sensitive bytes are written."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import BinaryIO

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_security_native as native


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL))


@contextmanager
def create_private_archive(path: Path) -> Iterator[BinaryIO]:
    native.require_windows()
    import msvcrt

    native.reject_reparse_components(path)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    convert.restype = wintypes.BOOL
    create = kernel.CreateFileW
    create.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    create.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel.LocalFree.restype = wintypes.HLOCAL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    if not convert("O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)", 1, ctypes.byref(descriptor), None):
        raise LifecycleError("cold_output_security", "cannot create private cold copy security")
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    try:
        # CREATE_NEW, no sharing, and a creation-time Admin/System-only DACL.
        handle = create(str(path), 0xC0000000, 0, ctypes.byref(attributes), 1, 0x00200080, None)
        error = ctypes.get_last_error()
    finally:
        kernel.LocalFree(descriptor)
    if handle == wintypes.HANDLE(-1).value:
        code = "cold_output_exists" if error in {80, 183} else "cold_output_security"
        raise LifecycleError(code, "cannot create a new private cold copy file")
    try:
        native.require_trusted_owner(path, code="cold_output_security", message="cold copy owner is not protected")
        if native._object_dacl_sddl(path) != native._canonical_dacl_sddl("D:P(A;;FA;;;SY)(A;;FA;;;BA)"):
            raise LifecycleError("cold_output_security", "cold copy file permissions are not private")
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDWR | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, "w+b") as stream:
        yield stream
