"""Create one private new archive handle before any sensitive bytes are written."""

from __future__ import annotations

import ctypes
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import BinaryIO

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_security_native as native


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL))


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = (("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD))


def _file_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
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
    kernel.SetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = (wintypes.HANDLE,)
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetFileInformationByHandleEx.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    return kernel


def _delete_on_close(kernel, handle: int, enabled: bool) -> None:
    disposition = ctypes.c_ubyte(enabled)
    if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
        raise LifecycleError("cold_output_security", "cannot set cold copy file disposition")


@contextmanager
def open_cold_source(path: Path) -> Iterator[BinaryIO]:
    """Hold a read lease across verification and use, excluding writers and rename."""
    native.require_windows()
    import msvcrt

    native.reject_reparse_components(path)
    kernel = _file_api()
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200080, None)
    if handle == wintypes.HANDLE(-1).value:
        raise LifecycleError("cold_source_unavailable", "cannot open a stable local file for reading")
    try:
        info = _FileAttributeTagInfo()
        if (kernel.GetFileType(handle) != 1  # FILE_TYPE_DISK
                or not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                or info.attributes & (stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_REPARSE_POINT)):
            raise LifecycleError("cold_source_unavailable", "select a regular local disk file")
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, "rb") as stream:
        yield stream


def _archive_sddl(independent: bool) -> str:
    owner = "BA"
    dacl = "D:P(A;;FA;;;SY)(A;;FA;;;BA)"
    if independent:
        owner = native.current_process_user_sid()
        if not owner:
            raise LifecycleError("cold_output_security", "cannot identify the local recovery operator")
        if owner not in {native.SYSTEM_SID, native.ADMINISTRATORS_SID}:
            dacl += f"(A;;FA;;;{owner})"
    return f"O:{owner}{dacl}"


def _require_handle_security(kernel, advapi, handle: int, expected) -> None:
    get = advapi.GetSecurityInfo
    get.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    get.restype = wintypes.DWORD
    owner_and_dacl = 0x5
    observed = ctypes.c_void_p()
    if get(handle, 1, owner_and_dacl, None, None, None, None, ctypes.byref(observed)):
        raise LifecycleError("cold_output_security", "cannot inspect the recovery file security")
    try:
        if native._security_descriptor_sddl(observed, owner_and_dacl) != native._security_descriptor_sddl(expected, owner_and_dacl):
            raise LifecycleError("cold_output_security", "unexpected recovery file owner or permissions")
    finally:
        kernel.LocalFree(observed)


@contextmanager
def create_private_archive(path: Path, *, independent: bool = False) -> Iterator[BinaryIO]:
    native.require_windows()
    import msvcrt

    native.reject_reparse_components(path)
    kernel = _file_api()
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    convert.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    if not convert(_archive_sddl(independent), 1, ctypes.byref(descriptor), None):
        raise LifecycleError("cold_output_security", "cannot create private cold copy security")
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    try:
        # CREATE_NEW, no sharing, protected DACL from the first byte.
        access = 0xC0010000 if independent else 0xC0000000
        handle = kernel.CreateFileW(str(path), access, 0, ctypes.byref(attributes), 1, 0x00200080, None)
        if handle == wintypes.HANDLE(-1).value:
            code = "cold_output_exists" if ctypes.get_last_error() in {80, 183} else "cold_output_security"
            raise LifecycleError(code, "cannot create a new private cold copy file")
        try:
            if independent:
                _delete_on_close(kernel, handle, True)
            _require_handle_security(kernel, advapi, handle, descriptor)
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    finally:
        kernel.LocalFree(descriptor)
    with os.fdopen(fd, "w+b") as stream:
        yield stream
        if independent:
            stream.flush()
            os.fsync(fd)
            _delete_on_close(kernel, handle, False)
