"""Coordinate per-user Manager ownership, binding, and runtime startup."""

from __future__ import annotations

import contextlib
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypeAlias

from backend_manager.app_controller import AppController
from backend_manager.config import ConfigError, MaintenanceManagerConfig, ManagerConfig
from backend_manager.control_server import (
    ControlServer,
    request_existing_manager_window,
)
from backend_manager.desktop_shell import open_app_window
from backend_manager.instance_owner import ManagerInstance, claim_manager_instance
from backend_manager.maintenance_gate import manager_maintenance_requested
from backend_manager.projection import UnavailableInstalledRuntimeConfigProvider
from backend_manager.runtime import RuntimeControlError
from backend_manager.runtime_factory import build_provider

_UI_HTML = Path(__file__).resolve().parent / "ui.html"
_PRODUCT_HTML = Path(__file__).resolve().parent / "product.html"
ManagerEndpointConfig: TypeAlias = ManagerConfig | MaintenanceManagerConfig


class _AppWindow(Protocol):
    def is_open(self) -> bool: ...
    def close(self, *, timeout: float = 5.0) -> bool: ...


class ManagerWindowSession:
    """Own every Edge process associated with one Manager instance."""

    def __init__(
        self,
        url: str,
        profile: Path,
        *,
        opener: Callable[..., _AppWindow | None] | None = None,
        bootstrapper: Callable[[Path], str] | None = None,
        bootstrap_canceller: Callable[[Path], None] | None = None,
    ) -> None:
        self._url = url
        self._profile = profile
        self._opener = opener or open_app_window
        self._bootstrapper = bootstrapper
        self._bootstrap_canceller = bootstrap_canceller
        self._windows: list[_AppWindow] = []
        self._lock = threading.Lock()
        self._closing = False
        self._next_window_id = 0

    def open(self) -> bool:
        with self._lock:
            if self._closing:
                return False
            self._next_window_id += 1
            window_profile = self._profile / f"window-{self._next_window_id:04d}"
            bootstrap_path = window_profile / "bootstrap.html"
            launch_url = (
                self._bootstrapper(bootstrap_path)
                if self._bootstrapper is not None
                else self._url
            )
            try:
                window = self._opener(launch_url, profile=window_profile)
            except BaseException:
                self._cancel_bootstrap(bootstrap_path)
                raise
            if window is None:
                self._cancel_bootstrap(bootstrap_path)
                return False
            self._windows = [existing for existing in self._windows if existing.is_open()]
            self._windows.append(window)
            return True

    def _cancel_bootstrap(self, path: Path) -> None:
        if self._bootstrapper is not None and self._bootstrap_canceller is not None:
            self._bootstrap_canceller(path)

    def has_open_windows(self) -> bool:
        with self._lock:
            self._windows = [window for window in self._windows if window.is_open()]
            return bool(self._windows)

    def close_all(self) -> bool:
        with self._lock:
            self._closing = True
            windows, self._windows = self._windows, []
        still_open: list[_AppWindow] = []
        for window in windows:
            if not window.close():
                still_open.append(window)
        if still_open:
            with self._lock:
                self._windows.extend(still_open)
        return not still_open

    def shutdown(self) -> None:
        if self.close_all():
            with contextlib.suppress(OSError):
                shutil.rmtree(self._profile)


def _build_runtime(config: ManagerEndpointConfig):
    if isinstance(config, MaintenanceManagerConfig):
        return (
            UnavailableInstalledRuntimeConfigProvider(),
            config.current_version,
            False,
            config.startup_failure_code,
            config.startup_failure_stage,
        )
    provider = build_provider(config)
    maintenance_version = (
        config.expected_backend_version if config.runtime_mode == "installed" else None
    )
    return provider, maintenance_version, config.runtime_mode == "source", None, None


def _bind_control_server(
    config: ManagerEndpointConfig,
    *,
    controller: AppController,
    token: str,
    instance_secret: str,
    request_window: Callable[[], bool],
) -> ControlServer:
    try:
        return ControlServer(
            config.manager_host,
            config.manager_port,
            controller=controller,
            token=token,
            instance_secret=instance_secret,
            ui_html=_UI_HTML,
            product_html=_PRODUCT_HTML,
            request_window=request_window,
        )
    except OSError:
        return ControlServer(
            config.manager_host,
            0,
            controller=controller,
            token=token,
            instance_secret=instance_secret,
            ui_html=_UI_HTML,
            product_html=_PRODUCT_HTML,
            request_window=request_window,
        )


def _wait_for_shutdown(
    *,
    controller: AppController,
    stop_event: threading.Event,
    shutdown_request: threading.Event,
    maintenance_requested,
    shutdown_grace_seconds: float,
    windows: ManagerWindowSession,
) -> None:
    shutdown_deadline: float | None = None
    while not stop_event.is_set():
        if maintenance_requested():
            if not shutdown_request.is_set():
                controller.request_manager_shutdown()
            if windows.close_all():
                stop_event.set()
                return
        if shutdown_request.is_set():
            if shutdown_deadline is None:
                shutdown_deadline = time.monotonic() + shutdown_grace_seconds
            if (
                not windows.has_open_windows() or time.monotonic() >= shutdown_deadline
            ) and windows.close_all():
                stop_event.set()
                return
        elif not windows.has_open_windows():
            stop_event.set()
            return
        time.sleep(0.1)


def reopen_existing_manager(
    config: ManagerEndpointConfig,
    instance: ManagerInstance,
    *,
    startup_timeout: float = 3.0,
) -> bool:
    deadline = time.monotonic() + startup_timeout
    while True:
        if manager_maintenance_requested():
            return True
        registration = instance.read_registration()
        if registration is not None and registration.port is not None:
            running_url = config.manager_url_for_port(registration.port)
        else:
            running_url = None
        if running_url and request_existing_manager_window(running_url, registration.secret):
            return True
        if instance.try_take_ownership():
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def run_owned_manager(
    config: ManagerEndpointConfig,
    instance: ManagerInstance,
    *,
    maintenance_requested=manager_maintenance_requested,
    shutdown_grace_seconds: float = 3.0,
) -> int:
    if instance.secret is None:
        raise ConfigError("无法建立小票夹管理器实例证明。")
    if maintenance_requested():
        return 0
    stop_event = threading.Event()
    shutdown_request = threading.Event()
    provider, maintenance_version, source_mode, startup_failure_code, startup_failure_stage = (
        _build_runtime(config)
    )
    controller = AppController(
        provider,
        maintenance_version=maintenance_version,
        startup_failure_code=startup_failure_code,
        startup_failure_stage=startup_failure_stage,
        request_shutdown=shutdown_request.set,
    )
    token = secrets.token_urlsafe(24)
    server: ControlServer | None = None
    server_thread: threading.Thread | None = None
    monitor_thread: threading.Thread | None = None
    windows: ManagerWindowSession | None = None
    server_started = False
    try:
        # Construction binds the socket before source runtime startup.
        server = _bind_control_server(
            config,
            controller=controller,
            token=token,
            instance_secret=instance.secret,
            request_window=lambda: False,
        )
        actual_port = int(server.server_address[1])
        instance.publish_port(actual_port)
        manager_url = config.manager_url_for_port(actual_port)
        windows = ManagerWindowSession(
            manager_url,
            instance.root / "edge-session",
            bootstrapper=server.prepare_web_bootstrap,
            bootstrap_canceller=server.cancel_web_bootstrap,
        )
        server.request_window = windows.open
        if source_mode:
            controller.start()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        server_started = True
        monitor_thread = threading.Thread(target=provider.run_monitor, args=(stop_event,), daemon=True)
        monitor_thread.start()
        if not windows.open():
            raise ConfigError("无法打开小票夹管理器窗口，请确认 Microsoft Edge 可用。")
        _wait_for_shutdown(
            controller=controller,
            stop_event=stop_event,
            shutdown_request=shutdown_request,
            maintenance_requested=maintenance_requested,
            shutdown_grace_seconds=shutdown_grace_seconds,
            windows=windows,
        )
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if windows is not None:
            windows.shutdown()
        if server is not None:
            if server_started:
                with contextlib.suppress(Exception):
                    server.shutdown()
            with contextlib.suppress(Exception):
                server.server_close()
        with contextlib.suppress(RuntimeControlError):
            provider.shutdown()
        if server_started and server_thread is not None:
            server_thread.join(timeout=5)
        if monitor_thread is not None:
            monitor_thread.join(timeout=5)
    return 0


def run_manager(config: ManagerEndpointConfig) -> int:
    if manager_maintenance_requested():
        return 0
    with claim_manager_instance() as instance:
        if not instance.is_owner:
            if reopen_existing_manager(config, instance):
                return 0
            if not instance.is_owner:
                raise ConfigError("已有同一 Windows 用户的小票夹管理器正在启动，但无法验证其控制界面。")
        return run_owned_manager(config, instance)
