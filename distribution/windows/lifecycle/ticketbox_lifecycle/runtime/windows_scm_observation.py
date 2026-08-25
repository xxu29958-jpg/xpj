from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol, TypeVar

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.windows_account import lookup_account_sid

_ERROR_INSUFFICIENT_BUFFER = 122
_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_CONFIG = 0x0001
_SERVICE_CONFIG_FAILURE_ACTIONS = 2
_SERVICE_CONFIG_DELAYED_AUTO_START_INFO = 3
_SERVICE_CONFIG_FAILURE_ACTIONS_FLAG = 4
_SERVICE_CONFIG_SERVICE_SID_INFO = 5
_SERVICE_CONFIG_TRIGGER_INFO = 8


@dataclass(frozen=True)
class FailureAction:
    action_type: int
    delay_ms: int


@dataclass(frozen=True)
class ServiceConfiguration:
    service_type: int
    start_type: int
    error_control: int
    argv: tuple[str, ...]
    load_order_group: str
    tag_id: int
    dependencies: tuple[str, ...]
    account_sid: str
    display_name: str
    sid_type: int
    failure_reset_seconds: int
    failure_actions: tuple[FailureAction, ...]
    failure_reboot_message: str
    failure_command: str
    failure_actions_on_non_crash: bool
    delayed_auto_start: bool
    trigger_count: int


class ScmObserver(Protocol):
    def observe(self, name: str) -> ServiceConfiguration: ...


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


class _ServiceSidInfo(ctypes.Structure):
    _fields_ = (("sid_type", wintypes.DWORD),)


class _ServiceFailureActionsFlag(ctypes.Structure):
    _fields_ = (("enabled", wintypes.BOOL),)


class _ServiceDelayedAutoStartInfo(ctypes.Structure):
    _fields_ = (("enabled", wintypes.BOOL),)


class _ServiceTriggerInfo(ctypes.Structure):
    _fields_ = (
        ("trigger_count", wintypes.DWORD),
        ("triggers", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
    )


_ConfigInfo = TypeVar("_ConfigInfo", bound=ctypes.Structure)


class NativeWindowsScmObserver:
    def observe(self, name: str) -> ServiceConfiguration:
        if os.name != "nt":
            raise LifecycleError("windows_required", "SCM observation requires Windows")
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        _declare_advapi32(advapi32)
        manager = advapi32.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
        if not manager:
            _raise_query("OpenSCManagerW")
        service = None
        try:
            service = advapi32.OpenServiceW(manager, name, _SERVICE_QUERY_CONFIG)
            if not service:
                _raise_query("OpenServiceW")
            base, base_buffer = _query_base(advapi32, service)
            sid = _query_info(advapi32, service, _SERVICE_CONFIG_SERVICE_SID_INFO, _ServiceSidInfo)
            failure = _query_info(
                advapi32,
                service,
                _SERVICE_CONFIG_FAILURE_ACTIONS,
                _ServiceFailureActionsW,
            )
            failure_flag = _query_info(
                advapi32,
                service,
                _SERVICE_CONFIG_FAILURE_ACTIONS_FLAG,
                _ServiceFailureActionsFlag,
            )
            delayed = _query_info(
                advapi32,
                service,
                _SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
                _ServiceDelayedAutoStartInfo,
            )
            triggers = _query_info(
                advapi32,
                service,
                _SERVICE_CONFIG_TRIGGER_INFO,
                _ServiceTriggerInfo,
            )
            actions = tuple(
                FailureAction(
                    action_type=int(failure.actions[index].action_type),
                    delay_ms=int(failure.actions[index].delay_ms),
                )
                for index in range(int(failure.action_count))
            )
            observed = ServiceConfiguration(
                service_type=int(base.service_type),
                start_type=int(base.start_type),
                error_control=int(base.error_control),
                argv=_command_line_argv(base.binary_path or ""),
                load_order_group=base.load_order_group or "",
                tag_id=int(base.tag_id),
                dependencies=_read_multisz(base.dependencies),
                account_sid=lookup_account_sid(base.account or ""),
                display_name=base.display_name or "",
                sid_type=int(sid.sid_type),
                failure_reset_seconds=int(failure.reset_seconds),
                failure_actions=actions,
                failure_reboot_message=failure.reboot_message or "",
                failure_command=failure.command or "",
                failure_actions_on_non_crash=bool(failure_flag.enabled),
                delayed_auto_start=bool(delayed.enabled),
                trigger_count=int(triggers.trigger_count),
            )
            del base_buffer
            return observed
        finally:
            if service:
                advapi32.CloseServiceHandle(service)
            advapi32.CloseServiceHandle(manager)


def _declare_advapi32(advapi32: object) -> None:
    advapi32.OpenSCManagerW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = (wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD)
    advapi32.OpenServiceW.restype = wintypes.HANDLE
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
        _raise_query("QueryServiceConfigW(size)")
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.QueryServiceConfigW(service, buffer, needed.value, ctypes.byref(needed)):
        _raise_query("QueryServiceConfigW")
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
        _raise_query(f"QueryServiceConfig2W({level},size)")
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.QueryServiceConfig2W(
        service,
        level,
        buffer,
        needed.value,
        ctypes.byref(needed),
    ):
        _raise_query(f"QueryServiceConfig2W({level})")
    value = ctypes.cast(buffer, ctypes.POINTER(structure)).contents
    value._buffer = buffer  # type: ignore[attr-defined]
    return value


def _command_line_argv(command_line: str) -> tuple[str, ...]:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    values = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not values:
        _raise_query("CommandLineToArgvW")
    try:
        return tuple(values[index] for index in range(count.value))
    finally:
        kernel32.LocalFree(ctypes.cast(values, wintypes.HLOCAL))


def _read_multisz(address: int | None) -> tuple[str, ...]:
    if not address:
        return ()
    values: list[str] = []
    offset = 0
    while True:
        value = ctypes.wstring_at(address + offset * ctypes.sizeof(ctypes.c_wchar))
        if not value:
            return tuple(values)
        values.append(value)
        offset += len(value) + 1


def _raise_query(operation: str) -> None:
    error = ctypes.get_last_error()
    raise LifecycleError("scm_query_failed", f"{operation} failed with Windows error {error}")
