"""Coordinate per-user Manager ownership, binding, and runtime startup."""

from __future__ import annotations

import contextlib
import secrets
import threading
import time
from pathlib import Path

from backend_manager.app_controller import AppController
from backend_manager.config import ConfigError, ManagerConfig
from backend_manager.control_server import ControlServer, manager_window_url, probe_existing_manager
from backend_manager.desktop_shell import open_app_window
from backend_manager.instance_owner import ManagerInstance, claim_manager_instance
from backend_manager.runtime import RuntimeControlError
from backend_manager.runtime_factory import build_provider

_UI_HTML = Path(__file__).resolve().parent / "ui.html"


def reopen_existing_manager(
    config: ManagerConfig,
    instance: ManagerInstance,
    *,
    startup_timeout: float = 3.0,
) -> bool:
    deadline = time.monotonic() + startup_timeout
    while True:
        registration = instance.read_registration()
        if registration is not None and registration.port is not None:
            running_url = config.manager_url_for_port(registration.port)
        else:
            running_url = None
        if running_url and probe_existing_manager(running_url, registration.secret):
            open_app_window(manager_window_url(running_url, registration.secret))
            return True
        if instance.try_take_ownership():
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def run_owned_manager(config: ManagerConfig, instance: ManagerInstance) -> int:
    if instance.secret is None:
        raise ConfigError("无法建立小票夹管理器实例证明。")
    provider = build_provider(config)
    controller = AppController(provider)
    stop_event = threading.Event()
    token = secrets.token_urlsafe(24)
    server: ControlServer | None = None
    server_thread: threading.Thread | None = None
    monitor_thread: threading.Thread | None = None
    server_started = False
    try:
        # Construction binds the socket before source runtime startup.
        try:
            server = ControlServer(
                config.manager_host,
                config.manager_port,
                controller=controller,
                token=token,
                instance_secret=instance.secret,
                ui_html=_UI_HTML,
            )
        except OSError:
            server = ControlServer(
                config.manager_host,
                0,
                controller=controller,
                token=token,
                instance_secret=instance.secret,
                ui_html=_UI_HTML,
            )
        actual_port = int(server.server_address[1])
        instance.publish_port(actual_port)
        manager_url = config.manager_url_for_port(actual_port)
        if config.runtime_mode == "source":
            controller.start()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        server_started = True
        monitor_thread = threading.Thread(target=provider.run_monitor, args=(stop_event,), daemon=True)
        monitor_thread.start()
        open_app_window(manager_window_url(manager_url, instance.secret))
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
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


def run_manager(config: ManagerConfig) -> int:
    with claim_manager_instance() as instance:
        if not instance.is_owner:
            if reopen_existing_manager(config, instance):
                return 0
            if not instance.is_owner:
                raise ConfigError("已有同一 Windows 用户的小票夹管理器正在启动，但无法验证其控制界面。")
        return run_owned_manager(config, instance)
