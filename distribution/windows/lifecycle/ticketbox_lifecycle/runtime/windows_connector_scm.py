"""Native SCM operations restricted to TicketboxCloudflared; no wrapper or shell."""

from __future__ import annotations

import ctypes
import subprocess
import time
from contextlib import contextmanager
from ctypes import wintypes

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.policy.connector_profile import FAILURE_ACTIONS, SERVICE_ACCOUNT, SERVICE_DACL, SERVICE_NAME
from ticketbox_lifecycle.runtime.windows_scm_observation import (
    _declare_advapi32,
    _ScAction,
    _ServiceFailureActionsW,
    _ServiceSidInfo,
)
from ticketbox_lifecycle.runtime.windows_security_native import _canonical_dacl_sddl, _security_descriptor_sddl


class _Status(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in (
        "service_type", "state", "controls", "exit_code", "service_exit_code", "checkpoint", "wait_hint", "pid", "flags",
    )]


def _error(action: str) -> None:
    error = ctypes.get_last_error()
    raise LifecycleError("connector_scm_failed", f"{action} failed (Windows error {error}); inspect the same operation")


def _declare(api: object) -> None:
    _declare_advapi32(api)
    api.CreateServiceW.argtypes = (wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        ctypes.c_void_p, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR)
    api.CreateServiceW.restype = wintypes.HANDLE
    api.ChangeServiceConfigW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPCWSTR, wintypes.LPCWSTR)
    api.ChangeServiceConfigW.restype = wintypes.BOOL
    api.ChangeServiceConfig2W.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p)
    api.ChangeServiceConfig2W.restype = wintypes.BOOL
    api.QueryServiceStatusEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    api.QueryServiceStatusEx.restype = wintypes.BOOL
    api.StartServiceW.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p)
    api.StartServiceW.restype = wintypes.BOOL
    api.ControlService.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p)
    api.ControlService.restype = wintypes.BOOL
    api.DeleteService.argtypes = (wintypes.HANDLE,)
    api.DeleteService.restype = wintypes.BOOL
    api.SetServiceObjectSecurity.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p)
    api.SetServiceObjectSecurity.restype = wintypes.BOOL
    api.QueryServiceObjectSecurity.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    api.QueryServiceObjectSecurity.restype = wintypes.BOOL
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL


class ConnectorScm:
    def __init__(self) -> None:
        self.api = ctypes.WinDLL("advapi32", use_last_error=True)
        _declare(self.api)

    @contextmanager
    def _open(self, access: int, *, optional: bool = False):
        manager = self.api.OpenSCManagerW(None, None, 1)
        if not manager:
            _error("OpenSCManagerW")
        service = None
        try:
            service = self.api.OpenServiceW(manager, SERVICE_NAME, access)
            if not service and not (optional and ctypes.get_last_error() == 1060):
                _error("OpenServiceW")
            yield service
        finally:
            if service:
                self.api.CloseServiceHandle(service)
            self.api.CloseServiceHandle(manager)

    def state_pid(self) -> tuple[int, int] | None:
        with self._open(4, optional=True) as service:
            if not service:
                return None
            status, needed = _Status(), wintypes.DWORD()
            if not self.api.QueryServiceStatusEx(service, 0, ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(needed)):
                _error("QueryServiceStatusEx")
            return int(status.state), int(status.pid)

    def create_stopped(self, argv: tuple[str, ...]) -> None:
        manager = self.api.OpenSCManagerW(None, None, 3)
        if not manager:
            _error("OpenSCManagerW(create)")
        service = None
        try:
            service = self.api.CreateServiceW(manager, SERVICE_NAME, SERVICE_NAME, 0xF01FF,
                16, 3, 1, subprocess.list2cmdline(argv), None, None, "", SERVICE_ACCOUNT, None)
            if not service:
                _error("CreateServiceW")
            self._set_policy(service)
        finally:
            if service:
                self.api.CloseServiceHandle(service)
            self.api.CloseServiceHandle(manager)
        if self.state_pid() != (1, 0):
            raise LifecycleError("connector_candidate_running", "new connector must be stopped before authorization")

    def prepare_generation(self, argv: tuple[str, ...]) -> None:
        self.disable_and_stop()
        with self._open(2) as service:
            if not self.api.ChangeServiceConfigW(service, 0xFFFFFFFF, 3, 0xFFFFFFFF,
                subprocess.list2cmdline(argv), None, None, None, None, None, None):
                _error("ChangeServiceConfigW(generation)")

    def finish_creation_policy(self) -> None:
        if self.state_pid() != (1, 0):
            raise LifecycleError("connector_candidate_running", "partial creation must be stopped before completing policy")
        # Restart recovery actions additionally require SERVICE_START.
        with self._open(2 | 0x10 | 0x40000) as service:
            self._set_policy(service)

    def set_start(self, start_type: int) -> None:
        if start_type not in {2, 3, 4}:
            raise ValueError("unsupported connector startup type")
        with self._open(2) as service:
            if not self.api.ChangeServiceConfigW(service, 0xFFFFFFFF, start_type, 0xFFFFFFFF,
                None, None, None, None, None, None, None):
                _error("ChangeServiceConfigW(start)")

    def disable_and_stop(self) -> None:
        self.set_start(4)
        current = self.state_pid()
        if current is not None and current[0] != 1:
            with self._open(0x20) as service:
                status = _Status()
                if not self.api.ControlService(service, 1, ctypes.byref(status)) and ctypes.get_last_error() != 1062:
                    _error("ControlService(stop)")
            self._wait(1)
        if self.state_pid() != (1, 0):
            raise LifecycleError("connector_stop_pending", "connector is not yet confirmed stopped")

    def enable_and_start(self) -> None:
        self.set_start(2)
        current = self.state_pid()
        if current is not None and current[0] == 4:
            return
        with self._open(0x10) as service:
            if not self.api.StartServiceW(service, 0, None) and ctypes.get_last_error() != 1056:
                _error("StartServiceW")
        self._wait(4)

    def delete_stopped(self) -> None:
        if self.state_pid() is None:
            return
        self.disable_and_stop()
        with self._open(0x10000) as service:
            if not self.api.DeleteService(service):
                _error("DeleteService")
        # Handles elsewhere may leave deletion pending; retain ownership/journal.
        try:
            remaining = self.state_pid()
        except LifecycleError as exc:
            raise LifecycleError("connector_delete_pending", "service deletion is pending; resume the same operation") from exc
        if remaining is not None:
            raise LifecycleError("connector_delete_pending", "service deletion is pending; resume the same operation")

    def _wait(self, expected: int) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            observed = self.state_pid()
            if observed is not None and observed[0] == expected:
                return
            if expected == 4 and observed is not None and observed[0] == 1:
                raise LifecycleError("connector_process_exited", "connector exited; public availability remains unverified")
            time.sleep(0.2)
        raise LifecycleError("connector_transition_pending", "connector transition timed out; query this operation")

    def _set_policy(self, service: int) -> None:
        sid = _ServiceSidInfo(1)
        if not self.api.ChangeServiceConfig2W(service, 5, ctypes.byref(sid)):
            _error("ChangeServiceConfig2W(SID)")
        actions = (_ScAction * len(FAILURE_ACTIONS))(*(_ScAction(item.action_type, item.delay_ms) for item in FAILURE_ACTIONS))
        failure = _ServiceFailureActionsW(0xFFFFFFFF, "", "", len(actions), actions)
        enabled = wintypes.BOOL(True)
        for level, data in ((2, failure), (4, enabled)):
            if not self.api.ChangeServiceConfig2W(service, level, ctypes.byref(data)):
                _error("ChangeServiceConfig2W(failure)")
        descriptor = ctypes.c_void_p()
        if not self.api.ConvertStringSecurityDescriptorToSecurityDescriptorW(SERVICE_DACL, 1, ctypes.byref(descriptor), None):
            _error("ConvertStringSecurityDescriptor")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel.LocalFree.restype = ctypes.c_void_p
        try:
            if not self.api.SetServiceObjectSecurity(service, 4, descriptor):
                _error("SetServiceObjectSecurity")
        finally:
            kernel.LocalFree(descriptor)
        self.require_dacl()

    def require_dacl(self) -> None:
        with self._open(0x20000) as service:
            needed = wintypes.DWORD()
            self.api.QueryServiceObjectSecurity(service, 4, None, 0, ctypes.byref(needed))
            if not 0 < needed.value <= 65536:
                _error("QueryServiceObjectSecurity(size)")
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.api.QueryServiceObjectSecurity(service, 4, buffer, len(buffer), ctypes.byref(needed)):
                _error("QueryServiceObjectSecurity")
            if _security_descriptor_sddl(buffer) != _canonical_dacl_sddl(SERVICE_DACL):
                raise LifecycleError("connector_scm_security_changed", "connector service DACL no longer matches its profile")
