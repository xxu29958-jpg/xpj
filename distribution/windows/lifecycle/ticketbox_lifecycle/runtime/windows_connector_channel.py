"""One local, PID-bound, explicitly secured pipe; only non-secret JSON crosses it."""

from __future__ import annotations

import ctypes
import json
import re
from contextlib import contextmanager
from ctypes import wintypes

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.windows_connector_peer import kernel_api

FRAME_LIMIT = 8192
CONNECT_SECONDS = 120
RESULT_SECONDS = 240
_CLIENT_ACCESS = 0x12019B  # File read/write without FILE_CREATE_PIPE_INSTANCE.


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL))


class _Overlapped(ctypes.Structure):
    _fields_ = (("internal", ctypes.c_size_t), ("internal_high", ctypes.c_size_t),
        ("offset", wintypes.DWORD), ("offset_high", wintypes.DWORD), ("event", wintypes.HANDLE))


def _pipe_name(channel_id: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", channel_id) is None:
        raise LifecycleViolation("connector_channel_invalid", "channel identifier is invalid")
    return "\\\\.\\pipe\\Ticketbox.Connector." + channel_id


def _sddl(sid: str) -> str:
    if re.fullmatch(r"S-1-(?:[0-9]+-)+[0-9]+", sid) is None:
        raise LifecycleViolation("connector_channel_invalid", "channel owner is invalid")
    return f"O:{sid}D:P(A;;FA;;;SY)(A;;0x12019b;;;BA)(A;;0x12019b;;;{sid})"


def _api():
    kernel = kernel_api()
    kernel.CreateNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_SecurityAttributes))
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetNamedPipeHandleState.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p)
    kernel.SetNamedPipeHandleState.restype = wintypes.BOOL
    kernel.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.ConnectNamedPipe.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Overlapped))
    kernel.ConnectNamedPipe.restype = wintypes.BOOL
    for name in ("ReadFile", "WriteFile"):
        method = getattr(kernel, name)
        method.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_Overlapped))
        method.restype = wintypes.BOOL
    kernel.GetOverlappedResult.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Overlapped), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL)
    kernel.GetOverlappedResult.restype = wintypes.BOOL
    kernel.CancelIoEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Overlapped))
    kernel.CancelIoEx.restype = wintypes.BOOL
    for name in ("GetNamedPipeServerProcessId", "GetNamedPipeClientProcessId"):
        getattr(kernel, name).argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        getattr(kernel, name).restype = wintypes.BOOL
    return kernel


def _descriptor_api():
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.GetSecurityInfo.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    advapi.GetSecurityInfo.restype = wintypes.DWORD
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (ctypes.c_void_p, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p)
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    return advapi


class ConnectorChannel:
    def __init__(self, handle) -> None:
        self.handle = handle
        self.kernel = _api()

    def require_security(self, sid: str) -> None:
        advapi = _descriptor_api()
        descriptor = ctypes.c_void_p()
        if advapi.GetSecurityInfo(self.handle, 1, 5, None, None, None, None, ctypes.byref(descriptor)):
            raise LifecycleViolation("connector_channel_security", "cannot inspect channel security")
        text = wintypes.LPWSTR()
        try:
            if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 5, ctypes.byref(text), None):
                raise ctypes.WinError(ctypes.get_last_error())
            # The pipe rights are deliberately not GENERIC_WRITE, which grants
            # an additional server instance on Windows named pipes.
            expected = _sddl(sid)
            if text.value.casefold() != expected.casefold():
                raise LifecycleViolation("connector_channel_security", "channel owner or explicit DACL changed")
        finally:
            if text:
                self.kernel.LocalFree(text)
            self.kernel.LocalFree(descriptor)

    def peer_pid(self, *, server: bool) -> int:
        pid = wintypes.DWORD()
        method = self.kernel.GetNamedPipeServerProcessId if server else self.kernel.GetNamedPipeClientProcessId
        if not method(self.handle, ctypes.byref(pid)):
            raise ctypes.WinError(ctypes.get_last_error())
        return pid.value

    def _io(self, kind: str, buffer, size: int, seconds: int) -> int:
        event = self.kernel.CreateEventW(None, True, False, None)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        overlapped = _Overlapped(event=event)
        transferred = wintypes.DWORD()
        try:
            if kind == "connect":
                success = self.kernel.ConnectNamedPipe(self.handle, ctypes.byref(overlapped))
            else:
                method = self.kernel.ReadFile if kind == "read" else self.kernel.WriteFile
                success = method(self.handle, buffer, size, ctypes.byref(transferred), ctypes.byref(overlapped))
            error = ctypes.get_last_error() if not success else 0
            if kind == "connect" and error == 535:
                return 0
            if not success and error != 997:
                raise LifecycleError("connector_channel_closed", "connector channel is unavailable")
            if not success and self.kernel.WaitForSingleObject(event, seconds * 1000) != 0:
                self.kernel.CancelIoEx(self.handle, ctypes.byref(overlapped))
                self.kernel.GetOverlappedResult(self.handle, ctypes.byref(overlapped), ctypes.byref(transferred), True)
                raise LifecycleError("connector_channel_timeout", "connector result is unknown; refresh its durable operation")
            if not self.kernel.GetOverlappedResult(self.handle, ctypes.byref(overlapped), ctypes.byref(transferred), False):
                raise LifecycleError("connector_channel_closed", "connector channel ended before a complete result")
            return transferred.value
        finally:
            self.kernel.CloseHandle(event)

    def accept(self) -> None:
        self._io("connect", None, 0, CONNECT_SECONDS)

    def send(self, payload: dict) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(raw) > FRAME_LIMIT:
            raise LifecycleViolation("connector_channel_limit", "connector message exceeds its fixed limit")
        buffer = ctypes.create_string_buffer(raw)
        if self._io("write", buffer, len(raw), 10) != len(raw):
            raise LifecycleError("connector_channel_closed", "connector message was not delivered completely")

    def receive(self, *, seconds: int = RESULT_SECONDS) -> dict:
        buffer = ctypes.create_string_buffer(FRAME_LIMIT + 1)
        size = self._io("read", buffer, len(buffer), seconds)
        if not 0 < size <= FRAME_LIMIT:
            raise LifecycleViolation("connector_channel_limit", "connector message is incomplete or oversized")
        try:
            payload = json.loads(buffer.raw[:size])
        except (ValueError, UnicodeError):
            raise LifecycleViolation("connector_channel_invalid", "connector message is invalid") from None
        if not isinstance(payload, dict):
            raise LifecycleViolation("connector_channel_invalid", "connector message must be an object")
        return payload


@contextmanager
def serve_channel(channel_id: str, sid: str):
    kernel, advapi = _api(), _descriptor_api()
    descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(_sddl(sid), 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    try:
        handle = kernel.CreateNamedPipeW(_pipe_name(channel_id), 0x40080003, 0xE, 1, FRAME_LIMIT, FRAME_LIMIT, 0,
            ctypes.byref(attributes))  # Overlapped, first instance, message mode, reject remote clients.
    finally:
        kernel.LocalFree(descriptor)
    if handle == wintypes.HANDLE(-1).value:
        raise LifecycleError("connector_channel_unavailable", "cannot create a private connector channel")
    try:
        channel = ConnectorChannel(handle)
        channel.require_security(sid)
        yield channel
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def connect_channel(channel_id: str):
    kernel = _api()
    # Identification-only SQOS prevents the ordinary server from impersonating
    # the elevated client. The helper never lends its privileged token.
    handle = kernel.CreateFileW(_pipe_name(channel_id), _CLIENT_ACCESS, 0, None, 3, 0x40110000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise LifecycleError("connector_channel_unavailable", "the initiating Manager channel is unavailable")
    try:
        mode = wintypes.DWORD(2)
        if not kernel.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        yield ConnectorChannel(handle)
    finally:
        kernel.CloseHandle(handle)
