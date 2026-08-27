"""Windows SCM read-only gateway and installed-service runtime."""

from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from backend_manager.health_probe import HealthProbeResult
from backend_manager.runtime import (
    RuntimeControlError,
    RuntimeStatus,
    ServiceAccessError,
)

_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SC_STATUS_PROCESS_INFO = 0
_ERROR_SERVICE_DOES_NOT_EXIST = 1060
_STATE_NAMES = {
    1: "stopped",
    2: "start_pending",
    3: "stop_pending",
    4: "running",
    5: "continue_pending",
    6: "pause_pending",
    7: "paused",
}


class _ServiceStatusProcess(ctypes.Structure):
    _fields_ = [
        ("service_type", ctypes.c_ulong),
        ("current_state", ctypes.c_ulong),
        ("controls_accepted", ctypes.c_ulong),
        ("win32_exit_code", ctypes.c_ulong),
        ("service_specific_exit_code", ctypes.c_ulong),
        ("check_point", ctypes.c_ulong),
        ("wait_hint", ctypes.c_ulong),
        ("process_id", ctypes.c_ulong),
        ("service_flags", ctypes.c_ulong),
    ]


@dataclass(frozen=True)
class ServiceSnapshot:
    name: str
    state: str
    pid: int | None = None
    checkpoint: int = 0
    wait_hint_ms: int = 0
    win32_exit_code: int = 0


class ServiceGateway(Protocol):
    def query(self, name: str) -> ServiceSnapshot: ...


class WindowsServiceGateway:
    """Locale-independent, query-only wrapper around the Windows SCM API."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeControlError("正式安装服务控制只支持 Windows。")
        self._advapi = ctypes.WinDLL("Advapi32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self._advapi.OpenSCManagerW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
        self._advapi.OpenSCManagerW.restype = ctypes.c_void_p
        self._advapi.OpenServiceW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
        self._advapi.OpenServiceW.restype = ctypes.c_void_p
        self._advapi.QueryServiceStatusEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self._advapi.QueryServiceStatusEx.restype = ctypes.c_int
        self._advapi.CloseServiceHandle.argtypes = [ctypes.c_void_p]
        self._advapi.CloseServiceHandle.restype = ctypes.c_int

    @contextmanager
    def _open_service(self, name: str, access: int):
        manager = self._advapi.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
        if not manager:
            raise ctypes.WinError(ctypes.get_last_error())
        service = None
        try:
            service = self._advapi.OpenServiceW(manager, name, access)
            if not service:
                raise ctypes.WinError(ctypes.get_last_error())
            yield service
        finally:
            if service:
                self._advapi.CloseServiceHandle(service)
            self._advapi.CloseServiceHandle(manager)

    def query(self, name: str) -> ServiceSnapshot:
        try:
            with self._open_service(name, _SERVICE_QUERY_STATUS) as service:
                status = _ServiceStatusProcess()
                needed = ctypes.c_ulong()
                ok = self._advapi.QueryServiceStatusEx(
                    service,
                    _SC_STATUS_PROCESS_INFO,
                    ctypes.cast(ctypes.byref(status), ctypes.POINTER(ctypes.c_ubyte)),
                    ctypes.sizeof(status),
                    ctypes.byref(needed),
                )
                if not ok:
                    raise ctypes.WinError(ctypes.get_last_error())
        except OSError as exc:
            if getattr(exc, "winerror", None) == _ERROR_SERVICE_DOES_NOT_EXIST:
                return ServiceSnapshot(name=name, state="missing")
            raise
        state = _STATE_NAMES.get(status.current_state, f"unknown_{status.current_state}")
        return ServiceSnapshot(
            name=name,
            state=state,
            pid=status.process_id or None,
            checkpoint=status.check_point,
            wait_hint_ms=status.wait_hint,
            win32_exit_code=status.win32_exit_code,
        )

class WindowsServiceRuntime:
    """Observe installer-owned backend and PostgreSQL services without mutation authority."""

    def __init__(
        self,
        *,
        gateway: ServiceGateway,
        backend_service_name: str,
        pg_service_name: str,
        health_probe: Callable[[], HealthProbeResult],
    ) -> None:
        self._gateway = gateway
        self._backend_service_name = backend_service_name
        self._pg_service_name = pg_service_name
        self._health_probe = health_probe

    def status(self) -> RuntimeStatus:
        backend = self._query(self._backend_service_name)
        database = self._query(self._pg_service_name)
        running = backend.state in {"running", "start_pending", "stop_pending"}
        if database.state != "running":
            health = HealthProbeResult(
                "pending" if database.state.endswith("_pending") else "stopped",
                f"PostgreSQL 服务未处于运行状态（当前：{database.state}），Ticketbox 暂不可用。",
            )
        elif backend.state == "running":
            health = self._health_probe()
        else:
            health = HealthProbeResult(
                "pending" if running else "stopped",
                "Ticketbox 后端服务正在切换状态。" if running else "Ticketbox 后端服务已停止。",
            )
        healthy = backend.state == "running" and database.state == "running" and health.healthy
        diagnostics = [
            self._service_diagnostic("后端", backend),
            self._service_diagnostic("PostgreSQL", database),
            f"健康检查：{health.detail}",
            "日志状态：受保护；管理器不读取或显示后端原始日志。",
        ]
        return RuntimeStatus(
            mode="installed",
            running=running,
            healthy=healthy,
            pid=backend.pid,
            uptime_seconds=0,
            auto_restart=True,
            auto_restart_configurable=False,
            restarts=0,
            backend_service_state=backend.state,
            database_service_state=database.state,
            log=diagnostics,
            control_error=None,
            health_state=health.state,
            health_detail=health.detail,
            mobile_endpoint_state=health.mobile_endpoint_state,
            android_binding_state=health.android_binding_state,
            iphone_upload_state=health.iphone_upload_state,
            runtime_access_state=health.runtime_access_state,
            owner_state=health.owner_state,
            owner_recovery_channel=health.owner_recovery_channel,
            service_controls_available=False,
        )

    def start(self) -> None:
        self._raise_control_unavailable()

    def stop(self) -> None:
        self._raise_control_unavailable()

    def restart(self) -> None:
        self._raise_control_unavailable()

    def toggle_auto_restart(self) -> bool:
        self._raise_control_unavailable()

    def run_monitor(self, stop_event: threading.Event) -> None:
        stop_event.wait()

    def shutdown(self) -> None:
        return

    @staticmethod
    def _raise_control_unavailable() -> None:
        raise RuntimeControlError("正式安装管理器只观察服务；生命周期控制保持 HOLD。")

    @staticmethod
    def _service_diagnostic(label: str, snapshot: ServiceSnapshot) -> str:
        pid = f"，PID {snapshot.pid}" if snapshot.pid else ""
        exit_detail = f"，Windows exit {snapshot.win32_exit_code}" if snapshot.win32_exit_code else ""
        return f"{label}服务 {snapshot.name}：{snapshot.state}{pid}{exit_detail}"

    def _query(self, name: str) -> ServiceSnapshot:
        try:
            return self._gateway.query(name)
        except OSError as exc:
            raise self._friendly_os_error("读取服务状态", exc) from exc

    @staticmethod
    def _friendly_os_error(action: str, exc: OSError) -> RuntimeControlError:
        error = getattr(exc, "winerror", None)
        if error == 5:
            return ServiceAccessError(f"{action}失败：Windows 拒绝访问，请修复安装或服务权限后重试。")
        detail = f"Windows error={error}" if error is not None else type(exc).__name__
        return RuntimeControlError(f"{action}失败（{detail}）；请刷新服务状态或修复安装后重试。")
