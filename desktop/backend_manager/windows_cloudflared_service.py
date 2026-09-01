"""Read one exact cloudflared Windows service without requesting mutation access."""

from __future__ import annotations

import ctypes
import ntpath
import os
import re
from contextlib import contextmanager
from ctypes import wintypes
from typing import Final, TypeVar

from backend_manager.cloudflared_contract import (
    CloudflaredProbeError,
    ServiceFailureAction,
    ServiceObservation,
)
from backend_manager.public_connectivity import ServiceState

_VERSION_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_SERVICE_DOES_NOT_EXIST = 1060
_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_CONFIG = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SC_STATUS_PROCESS_INFO = 0
_SERVICE_CONFIG_FAILURE_ACTIONS = 2

_STATE_NAMES: Final = {
    1: ServiceState.STOPPED,
    2: ServiceState.START_PENDING,
    3: ServiceState.STOP_PENDING,
    4: ServiceState.RUNNING,
}


class _ServiceStatusProcess(ctypes.Structure):
    _fields_ = (
        ("service_type", wintypes.DWORD),
        ("current_state", wintypes.DWORD),
        ("controls_accepted", wintypes.DWORD),
        ("win32_exit_code", wintypes.DWORD),
        ("service_specific_exit_code", wintypes.DWORD),
        ("check_point", wintypes.DWORD),
        ("wait_hint", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("service_flags", wintypes.DWORD),
    )


class _QueryServiceConfigW(ctypes.Structure):
    _fields_ = (
        ("service_type", wintypes.DWORD),
        ("start_type", wintypes.DWORD),
        ("error_control", wintypes.DWORD),
        ("binary_path", wintypes.LPWSTR),
        ("load_order_group", wintypes.LPWSTR),
        ("tag_id", wintypes.DWORD),
        ("dependencies", ctypes.c_void_p),
        ("account", wintypes.LPWSTR),
        ("display_name", wintypes.LPWSTR),
    )


class _ScAction(ctypes.Structure):
    _fields_ = (("action_type", wintypes.DWORD), ("delay_ms", wintypes.DWORD))


class _ServiceFailureActionsW(ctypes.Structure):
    _fields_ = (
        ("reset_seconds", wintypes.DWORD),
        ("reboot_message", wintypes.LPWSTR),
        ("command", wintypes.LPWSTR),
        ("action_count", wintypes.DWORD),
        ("actions", ctypes.POINTER(_ScAction)),
    )


_ConfigInfo = TypeVar("_ConfigInfo", bound=ctypes.Structure)


class WindowsCloudflaredServiceReader:
    """Locale-independent exact-name SCM reader with no mutation access."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise CloudflaredProbeError("Windows SCM observation is unavailable")
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        _declare_advapi32(self._advapi)

    def read_exact(self, service_name: str) -> ServiceObservation:
        name = service_name.strip()
        if not name or len(name) > 256 or any(character in name for character in "*?[]"):
            raise CloudflaredProbeError("invalid exact service name")
        try:
            with self._open_service(name) as service:
                status = self._query_status(service)
                base, base_buffer = _query_base(self._advapi, service)
                failure = _query_info(
                    self._advapi,
                    service,
                    _SERVICE_CONFIG_FAILURE_ACTIONS,
                    _ServiceFailureActionsW,
                )
                actions = tuple(
                    ServiceFailureAction(
                        action_type=int(failure.actions[index].action_type),
                        delay_ms=int(failure.actions[index].delay_ms),
                    )
                    for index in range(int(failure.action_count))
                )
                observation = ServiceObservation(
                    exists=True,
                    state=_STATE_NAMES.get(int(status.current_state), ServiceState.FAILED),
                    argv=_command_line_argv(base.binary_path or ""),
                    account=(base.account or "").strip() or None,
                    start_type=int(base.start_type),
                    failure_reset_period_seconds=int(failure.reset_seconds),
                    failure_actions=actions,
                    executable_version=_file_version_from_argv(base.binary_path or ""),
                )
                del base_buffer
                return observation
        except OSError as exc:
            if getattr(exc, "winerror", None) == _ERROR_SERVICE_DOES_NOT_EXIST:
                return ServiceObservation.missing()
            raise CloudflaredProbeError("Windows SCM observation failed") from None

    @contextmanager
    def _open_service(self, service_name: str):
        manager = self._advapi.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
        if not manager:
            raise ctypes.WinError(ctypes.get_last_error())
        service = None
        try:
            service = self._advapi.OpenServiceW(
                manager,
                service_name,
                _SERVICE_QUERY_CONFIG | _SERVICE_QUERY_STATUS,
            )
            if not service:
                raise ctypes.WinError(ctypes.get_last_error())
            yield service
        finally:
            if service:
                self._advapi.CloseServiceHandle(service)
            self._advapi.CloseServiceHandle(manager)

    def _query_status(self, service: int) -> _ServiceStatusProcess:
        status = _ServiceStatusProcess()
        needed = wintypes.DWORD()
        if not self._advapi.QueryServiceStatusEx(
            service,
            _SC_STATUS_PROCESS_INFO,
            ctypes.cast(ctypes.byref(status), ctypes.POINTER(ctypes.c_ubyte)),
            ctypes.sizeof(status),
            ctypes.byref(needed),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return status


def _declare_advapi32(advapi32: object) -> None:
    advapi32.OpenSCManagerW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = (wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD)
    advapi32.OpenServiceW.restype = wintypes.HANDLE
    advapi32.QueryServiceStatusEx.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_ubyte),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
    advapi32.QueryServiceConfigW.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.QueryServiceConfigW.restype = wintypes.BOOL
    advapi32.QueryServiceConfig2W.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.QueryServiceConfig2W.restype = wintypes.BOOL
    advapi32.CloseServiceHandle.argtypes = (wintypes.HANDLE,)
    advapi32.CloseServiceHandle.restype = wintypes.BOOL


def _query_base(advapi32: object, service: int) -> tuple[_QueryServiceConfigW, object]:
    needed = wintypes.DWORD()
    advapi32.QueryServiceConfigW(service, None, 0, ctypes.byref(needed))
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or needed.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.QueryServiceConfigW(service, buffer, needed.value, ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.cast(buffer, ctypes.POINTER(_QueryServiceConfigW)).contents, buffer


def _query_info(
    advapi32: object,
    service: int,
    level: int,
    structure: type[_ConfigInfo],
) -> _ConfigInfo:
    needed = wintypes.DWORD()
    advapi32.QueryServiceConfig2W(service, level, None, 0, ctypes.byref(needed))
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or needed.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.QueryServiceConfig2W(
        service,
        level,
        buffer,
        needed.value,
        ctypes.byref(needed),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    value = ctypes.cast(buffer, ctypes.POINTER(structure)).contents
    value._buffer = buffer  # type: ignore[attr-defined]
    return value


def _command_line_argv(command_line: str) -> tuple[str, ...]:
    if not command_line:
        return ()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    values = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not values:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return tuple(values[index] for index in range(count.value))
    finally:
        kernel32.LocalFree(ctypes.cast(values, wintypes.HLOCAL))


def _file_version_from_argv(command_line: str) -> str | None:
    """Read a trusted file version resource without executing the binary."""

    try:
        argv = _command_line_argv(command_line)
    except OSError:
        return None
    if not argv or not ntpath.isabs(argv[0]) or argv[0].startswith(("\\\\", "//")):
        return None
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        )
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = (
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        )
        version.VerQueryValueW.restype = wintypes.BOOL
        ignored = wintypes.DWORD()
        size = version.GetFileVersionInfoSizeW(argv[0], ctypes.byref(ignored))
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(argv[0], 0, size, buffer):
            return None

        class _FixedFileInfo(ctypes.Structure):
            _fields_ = (
                ("signature", wintypes.DWORD),
                ("struct_version", wintypes.DWORD),
                ("file_version_ms", wintypes.DWORD),
                ("file_version_ls", wintypes.DWORD),
                ("product_version_ms", wintypes.DWORD),
                ("product_version_ls", wintypes.DWORD),
                ("file_flags_mask", wintypes.DWORD),
                ("file_flags", wintypes.DWORD),
                ("file_os", wintypes.DWORD),
                ("file_type", wintypes.DWORD),
                ("file_subtype", wintypes.DWORD),
                ("file_date_ms", wintypes.DWORD),
                ("file_date_ls", wintypes.DWORD),
            )

        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
        if info.signature != 0xFEEF04BD:
            return None
        parts = (
            info.file_version_ms >> 16,
            info.file_version_ms & 0xFFFF,
            info.file_version_ls >> 16,
            info.file_version_ls & 0xFFFF,
        )
        candidate = ".".join(str(part) for part in parts)
        return candidate if _VERSION_PATTERN.fullmatch(candidate) else None
    except (AttributeError, OSError, ValueError):
        return None
