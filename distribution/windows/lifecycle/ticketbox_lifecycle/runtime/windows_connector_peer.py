"""Retained process identity for the one-shot Manager/Lifecycle channel."""

from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleViolation


@dataclass(frozen=True)
class Peer:
    pid: int
    image: Path
    sid: str
    session: int
    elevated: bool


def kernel_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    return kernel


def _token_information(advapi, token, kind: int):
    size = wintypes.DWORD()
    advapi.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
    if not 0 < size.value <= 65536:
        raise LifecycleViolation("connector_peer_invalid", "cannot inspect channel peer token")
    value = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(token, kind, value, size, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return value


def _token_identity(kernel, process) -> tuple[str, int, bool]:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(process, 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        user = _token_information(advapi, token, 1)
        sid = ctypes.cast(user, ctypes.POINTER(ctypes.c_void_p))[0]
        text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid_text = text.value
        finally:
            kernel.LocalFree(text)
        session = wintypes.DWORD.from_buffer(_token_information(advapi, token, 12)).value
        elevated = bool(wintypes.DWORD.from_buffer(_token_information(advapi, token, 20)).value)
        return sid_text, session, elevated
    finally:
        kernel.CloseHandle(token)


@contextmanager
def hold_peer(pid: int):
    """Pin the process object until the request/result exchange has finished."""
    kernel = kernel_api()
    process = kernel.OpenProcess(0x101000, False, pid)
    if not process:
        raise LifecycleViolation("connector_peer_missing", "channel peer is no longer available")
    try:
        if kernel.WaitForSingleObject(process, 0) != 258:
            raise LifecycleViolation("connector_peer_missing", "channel peer has exited")
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(process, 0, image, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid, session, elevated = _token_identity(kernel, process)
        yield Peer(pid, Path(image.value), sid, session, elevated)
    finally:
        kernel.CloseHandle(process)


def require_peer(peer: Peer, expected_image: Path, *, session: int, elevated: bool, sid: str | None = None) -> None:
    if (os.path.normcase(str(peer.image)) != os.path.normcase(str(expected_image)) or
        peer.session != session or peer.elevated is not elevated or sid is not None and peer.sid != sid):
        raise LifecycleViolation("connector_peer_mismatch", "channel peer does not match the installed process and session")
