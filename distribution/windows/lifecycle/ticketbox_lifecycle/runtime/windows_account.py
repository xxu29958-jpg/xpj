from __future__ import annotations

import ctypes
from ctypes import wintypes

from ticketbox_lifecycle.errors import LifecycleError

_ERROR_INSUFFICIENT_BUFFER = 122


def lookup_account_sid(account: str) -> str:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.LookupAccountNameW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.LookupAccountNameW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    sid_size = wintypes.DWORD()
    domain_size = wintypes.DWORD()
    sid_use = wintypes.DWORD()
    advapi32.LookupAccountNameW(
        None,
        account,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    )
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or sid_size.value == 0:
        _raise_lookup()
    sid = ctypes.create_string_buffer(sid_size.value)
    domain = ctypes.create_unicode_buffer(domain_size.value)
    if not advapi32.LookupAccountNameW(
        None,
        account,
        sid,
        ctypes.byref(sid_size),
        domain,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    ):
        _raise_lookup()
    text = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        _raise_lookup()
    try:
        return str(text.value)
    finally:
        kernel32.LocalFree(text)


def _raise_lookup() -> None:
    raise LifecycleError(
        "scm_account_lookup_failed",
        f"cannot resolve service account SID (Windows error {ctypes.get_last_error()})",
    )
