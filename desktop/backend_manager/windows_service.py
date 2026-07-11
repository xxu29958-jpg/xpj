"""Windows SCM gateway and installed-service runtime."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from backend_manager.process import HealthProbeResult
from backend_manager.runtime import (
    RuntimeControlError,
    RuntimeStatus,
    ServiceAccessError,
    ServiceMissingError,
    ServiceTransitionError,
)

_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SERVICE_START = 0x0010
_SERVICE_STOP = 0x0020
_SERVICE_CONTROL_STOP = 0x00000001
_SC_STATUS_PROCESS_INFO = 0
_ERROR_SERVICE_DOES_NOT_EXIST = 1060
_ERROR_SERVICE_ALREADY_RUNNING = 1056
_ERROR_SERVICE_NOT_ACTIVE = 1062
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


class _ServiceStatus(ctypes.Structure):
    _fields_ = [
        ("service_type", ctypes.c_ulong),
        ("current_state", ctypes.c_ulong),
        ("controls_accepted", ctypes.c_ulong),
        ("win32_exit_code", ctypes.c_ulong),
        ("service_specific_exit_code", ctypes.c_ulong),
        ("check_point", ctypes.c_ulong),
        ("wait_hint", ctypes.c_ulong),
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
    def start(self, name: str) -> None: ...
    def stop(self, name: str) -> None: ...


class ServiceActionRunner(Protocol):
    def run(self, action: str) -> None: ...


class WindowsServiceGateway:
    """Small locale-independent wrapper around the Windows Service Control Manager API."""

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
        self._advapi.StartServiceW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        self._advapi.StartServiceW.restype = ctypes.c_int
        self._advapi.ControlService.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_ServiceStatus),
        ]
        self._advapi.ControlService.restype = ctypes.c_int
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

    def start(self, name: str) -> None:
        with self._open_service(name, _SERVICE_START | _SERVICE_QUERY_STATUS) as service:
            if not self._advapi.StartServiceW(service, 0, None):
                error = ctypes.get_last_error()
                if error != _ERROR_SERVICE_ALREADY_RUNNING:
                    raise ctypes.WinError(error)

    def stop(self, name: str) -> None:
        with self._open_service(name, _SERVICE_STOP | _SERVICE_QUERY_STATUS) as service:
            status = _ServiceStatus()
            if not self._advapi.ControlService(service, _SERVICE_CONTROL_STOP, ctypes.byref(status)):
                error = ctypes.get_last_error()
                if error != _ERROR_SERVICE_NOT_ACTIVE:
                    raise ctypes.WinError(error)


class WindowsServiceRuntime:
    """Control the installer-owned backend service while observing its PG dependency."""

    def __init__(
        self,
        *,
        gateway: ServiceGateway,
        backend_service_name: str,
        pg_service_name: str,
        health_probe: Callable[[], HealthProbeResult],
        wait_timeout_seconds: float,
        pg_wait_timeout_seconds: float,
        poll_seconds: float,
        backend_ready_timeout_seconds: float,
        backend_ready_poll_seconds: float,
        clock=time.monotonic,
        sleep=time.sleep,
        backend_stopped_validator: Callable[[], None] | None = None,
    ) -> None:
        self._gateway = gateway
        self._backend_service_name = backend_service_name
        self._pg_service_name = pg_service_name
        self._health_probe = health_probe
        self._wait_timeout_seconds = wait_timeout_seconds
        self._pg_wait_timeout_seconds = pg_wait_timeout_seconds
        self._poll_seconds = poll_seconds
        self._backend_ready_timeout_seconds = backend_ready_timeout_seconds
        self._backend_ready_poll_seconds = backend_ready_poll_seconds
        self._clock = clock
        self._sleep = sleep
        self._backend_stopped_validator = backend_stopped_validator or (lambda: None)
        self._lock = threading.RLock()

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
        )

    def start(self) -> None:
        with self._lock:
            self._run_control(self._start_services)

    def _start_services(self) -> None:
        self._ensure_started(self._pg_service_name, self._pg_wait_timeout_seconds)
        self._ensure_started(self._backend_service_name, self._wait_timeout_seconds)
        self._wait_for_backend_health()

    def stop(self) -> None:
        with self._lock:
            self._run_control(self._stop_backend)

    def _stop_backend(self) -> None:
        self._ensure_stopped(self._backend_service_name, self._wait_timeout_seconds)
        self._backend_stopped_validator()

    def restart(self) -> None:
        with self._lock:
            self._run_control(self._restart_services)

    def _restart_services(self) -> None:
        self._stop_backend()
        self._start_services()

    def toggle_auto_restart(self) -> bool:
        return True

    def run_monitor(self, stop_event: threading.Event) -> None:
        stop_event.wait()

    def shutdown(self) -> None:
        return

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

    def _ensure_started(self, name: str, timeout_seconds: float) -> None:
        snapshot = self._query(name)
        self._require_present(snapshot)
        if snapshot.state == "running":
            return
        if snapshot.state == "start_pending":
            self._wait_for(name, "running", timeout_seconds)
            return
        if snapshot.state == "stop_pending":
            self._wait_for(name, "stopped", timeout_seconds)
        elif snapshot.state != "stopped":
            raise ServiceTransitionError(f"服务 {name} 当前状态为 {snapshot.state}，无法启动。")
        self._gateway.start(name)
        self._wait_for(name, "running", timeout_seconds)

    def _ensure_stopped(self, name: str, timeout_seconds: float) -> None:
        snapshot = self._query(name)
        self._require_present(snapshot)
        if snapshot.state == "stopped":
            return
        if snapshot.state == "stop_pending":
            self._wait_for(name, "stopped", timeout_seconds)
            return
        if snapshot.state == "start_pending":
            snapshot = self._wait_for_any(name, {"running", "stopped"}, timeout_seconds)
            if snapshot.state == "stopped":
                return
        elif snapshot.state != "running":
            raise ServiceTransitionError(f"服务 {name} 当前状态为 {snapshot.state}，无法停止。")
        self._gateway.stop(name)
        self._wait_for(name, "stopped", timeout_seconds)

    def _wait_for(self, name: str, target: str, timeout_seconds: float) -> ServiceSnapshot:
        return self._wait_for_any(name, {target}, timeout_seconds)

    def _wait_for_any(self, name: str, targets: set[str], timeout_seconds: float) -> ServiceSnapshot:
        hard_deadline = self._clock() + timeout_seconds
        checkpoint_deadline = hard_deadline
        last_checkpoint = 0
        while self._clock() < hard_deadline:
            snapshot = self._query(name)
            self._require_present(snapshot)
            if snapshot.state in targets:
                return snapshot
            if targets == {"running"} and snapshot.state == "stopped" and snapshot.win32_exit_code:
                raise ServiceTransitionError(
                    f"服务 {name} 启动失败（Windows exit={snapshot.win32_exit_code}）。",
                )
            if snapshot.checkpoint > last_checkpoint:
                last_checkpoint = snapshot.checkpoint
                progress_window = max(snapshot.wait_hint_ms / 1000.0, self._poll_seconds * 2, 1.0)
                checkpoint_deadline = min(hard_deadline, self._clock() + progress_window)
            if last_checkpoint and self._clock() >= checkpoint_deadline:
                break
            remaining = hard_deadline - self._clock()
            if remaining > 0:
                self._sleep(min(self._poll_seconds, remaining))
        state = self._query(name).state
        target_text = "/".join(sorted(targets))
        raise ServiceTransitionError(
            f"服务 {name} 未在 {timeout_seconds:g} 秒内进入 {target_text}，当前状态：{state}，checkpoint={last_checkpoint}。",
        )

    def _wait_for_backend_health(self) -> None:
        deadline = self._clock() + self._backend_ready_timeout_seconds
        last = HealthProbeResult("pending", "Ticketbox 后端身份检查尚未开始。")
        while self._clock() < deadline:
            last = self._health_probe()
            if last.healthy:
                return
            if last.state == "mismatch":
                raise ServiceTransitionError(last.detail)
            remaining = deadline - self._clock()
            if remaining > 0:
                self._sleep(min(self._backend_ready_poll_seconds, remaining))
        raise ServiceTransitionError(
            f"Ticketbox 后端未在 {self._backend_ready_timeout_seconds:g} 秒内通过身份就绪检查：{last.detail}",
        )

    @staticmethod
    def _require_present(snapshot: ServiceSnapshot) -> None:
        if snapshot.state == "missing":
            raise ServiceMissingError(f"未找到 Windows 服务 {snapshot.name}，请修复或重新安装小票夹。")

    def _run_control(self, action) -> None:
        try:
            action()
        except RuntimeControlError:
            raise
        except OSError as exc:
            raise self._friendly_os_error("控制 Windows 服务", exc) from exc

    @staticmethod
    def _friendly_os_error(action: str, exc: OSError) -> RuntimeControlError:
        error = getattr(exc, "winerror", None)
        if error == 5:
            return ServiceAccessError(f"{action}失败：Windows 拒绝访问，请修复安装或服务权限后重试。")
        detail = f"Windows error={error}" if error is not None else type(exc).__name__
        return RuntimeControlError(f"{action}失败（{detail}）；请刷新服务状态或修复安装后重试。")


class BrokeredWindowsServiceRuntime:
    """Read status unelevated and delegate each mutation to a short-lived UAC helper."""

    def __init__(self, status_runtime: WindowsServiceRuntime, action_runner: ServiceActionRunner) -> None:
        self._status_runtime = status_runtime
        self._action_runner = action_runner

    def status(self) -> RuntimeStatus:
        return self._status_runtime.status()

    def start(self) -> None:
        self._action_runner.run("start")

    def stop(self) -> None:
        self._action_runner.run("stop")

    def restart(self) -> None:
        self._action_runner.run("restart")

    def toggle_auto_restart(self) -> bool:
        return True

    def run_monitor(self, stop_event: threading.Event) -> None:
        stop_event.wait()

    def shutdown(self) -> None:
        return
