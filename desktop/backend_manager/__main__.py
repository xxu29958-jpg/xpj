"""Desktop Manager entry point for source and installed-service runtimes."""

from __future__ import annotations

import argparse
import contextlib
import secrets
import shutil
import subprocess
import threading
import time
from functools import partial
from pathlib import Path

from backend_manager.config import ConfigError, InstalledRuntimeConfig, ManagerConfig, SourceRuntimeConfig, load_config
from backend_manager.control_server import ControlServer
from backend_manager.elevation import (
    HELPER_EXIT_ACCESS,
    HELPER_EXIT_CONFIG,
    HELPER_EXIT_MISSING_SERVICE,
    HELPER_EXIT_NOT_ELEVATED,
    HELPER_EXIT_OS,
    HELPER_EXIT_TRANSITION,
    ElevatedServiceActionRunner,
    ServiceAction,
    is_process_elevated,
    start_helper_watchdog,
)
from backend_manager.netinfo import lan_ip
from backend_manager.process import (
    health_ok,
    spawn_backend,
    tree_kill,
)
from backend_manager.runtime import (
    BackendRuntime,
    RuntimeControlError,
    RuntimeStatus,
    ServiceAccessError,
    ServiceMissingError,
    ServiceTransitionError,
    SourceBackendRuntime,
)
from backend_manager.supervisor import BackendSupervisor
from backend_manager.windows_service import (
    BrokeredWindowsServiceRuntime,
    WindowsServiceGateway,
    WindowsServiceRuntime,
)

_CREATE_NO_WINDOW = 0x08000000
_EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
_UI_HTML = Path(__file__).resolve().parent / "ui.html"


def _open_in_browser(url: str) -> None:
    with contextlib.suppress(OSError):
        subprocess.Popen(["cmd", "/c", "start", "", url], creationflags=_CREATE_NO_WINDOW)


def _open_app_window(url: str) -> None:
    """Open the UI as a chromeless Edge ``--app`` window, falling back to the default browser."""
    edge = next((c for c in (*_EDGE_CANDIDATES, shutil.which("msedge")) if c and Path(c).exists()), None)
    if edge is None:
        _open_in_browser(url)
        return
    try:
        subprocess.Popen([edge, f"--app={url}", "--window-size=820,660"], creationflags=_CREATE_NO_WINDOW)
    except OSError:
        _open_in_browser(url)


class AppController:
    """Adapt one runtime into the stable JSON contract consumed by ``ui.html``."""

    def __init__(self, runtime: BackendRuntime, config: ManagerConfig) -> None:
        self._runtime = runtime
        self._config = config
        self._last_error: str | None = None
        self._lock = threading.RLock()

    def status(self) -> dict:
        status_error: str | None = None
        try:
            snapshot = self._runtime.status()
        except RuntimeControlError as exc:
            status_error = str(exc)
            snapshot = self._unavailable_status()
        ip = lan_ip()
        port = self._config.backend_port
        with self._lock:
            last_error = status_error or snapshot.control_error or self._last_error
        return {
            "runtime_mode": snapshot.mode,
            "running": snapshot.running,
            "health": snapshot.healthy,
            "uptime_seconds": snapshot.uptime_seconds,
            "pid": snapshot.pid,
            "port": port,
            "auto_restart": snapshot.auto_restart,
            "auto_restart_configurable": snapshot.auto_restart_configurable,
            "restarts": snapshot.restarts,
            "backend_service_state": snapshot.backend_service_state,
            "database_service_state": snapshot.database_service_state,
            "lan": f"{ip}:{port}" if ip else "未发现局域网地址",
            "tunnel": self._config.public_base_url,
            "owner_url": self._config.owner_url,
            "log": snapshot.log,
            "control_error": last_error,
        }

    def start(self) -> None:
        self._control(self._runtime.start)

    def stop(self) -> None:
        self._control(self._runtime.stop)

    def restart(self) -> None:
        self._control(self._runtime.restart)

    def auto_restart(self) -> None:
        self._control(self._runtime.toggle_auto_restart)

    def open_console(self) -> None:
        _open_in_browser(self._config.owner_url)

    def _control(self, action) -> None:
        try:
            action()
        except RuntimeControlError as exc:
            with self._lock:
                self._last_error = str(exc)
        else:
            with self._lock:
                self._last_error = None

    def _unavailable_status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode=self._config.runtime_mode,
            running=False,
            healthy=False,
            pid=None,
            uptime_seconds=0,
            auto_restart=self._config.runtime_mode == "installed",
            auto_restart_configurable=self._config.runtime_mode == "source",
            restarts=0,
            backend_service_state="unknown" if self._config.runtime_mode == "installed" else None,
            database_service_state="unknown" if self._config.runtime_mode == "installed" else None,
            log=[],
            control_error=None,
        )


def _build_source_supervisor(config: ManagerConfig, runtime: SourceRuntimeConfig) -> BackendSupervisor:
    return BackendSupervisor(
        spawn=partial(
            spawn_backend,
            backend_root=runtime.backend_root,
            venv_python=runtime.venv_python,
            host=config.backend_host,
            port=config.backend_port,
        ),
        tree_kill=tree_kill,
        health=partial(health_ok, config.health_url),
    )


def _build_direct_service_runtime(config: ManagerConfig, runtime: InstalledRuntimeConfig) -> WindowsServiceRuntime:
    return WindowsServiceRuntime(
        gateway=WindowsServiceGateway(),
        backend_service_name=runtime.backend_service_name,
        pg_service_name=runtime.pg_service_name,
        health_url=config.health_url,
        log_path=runtime.log_path,
    )


def _build_runtime(config: ManagerConfig) -> BackendRuntime:
    runtime = config.runtime
    if isinstance(runtime, SourceRuntimeConfig):
        return SourceBackendRuntime(_build_source_supervisor(config, runtime))
    if isinstance(runtime, InstalledRuntimeConfig):
        return BrokeredWindowsServiceRuntime(
            status_runtime=_build_direct_service_runtime(config, runtime),
            action_runner=ElevatedServiceActionRunner(),
        )
    raise ConfigError(f"unsupported runtime: {type(runtime).__name__}")


def _run_elevated_service_action(action: ServiceAction) -> int:
    if not is_process_elevated():
        return HELPER_EXIT_NOT_ELEVATED
    watchdog = start_helper_watchdog()
    try:
        config = load_config(mode_override="installed")
        runtime_config = config.runtime
        if not isinstance(runtime_config, InstalledRuntimeConfig):
            return HELPER_EXIT_CONFIG
        runtime = _build_direct_service_runtime(config, runtime_config)
        getattr(runtime, action)()
        return 0
    except ConfigError:
        return HELPER_EXIT_CONFIG
    except ServiceMissingError:
        return HELPER_EXIT_MISSING_SERVICE
    except ServiceTransitionError:
        return HELPER_EXIT_TRANSITION
    except ServiceAccessError:
        return HELPER_EXIT_ACCESS
    except (OSError, RuntimeControlError):
        return HELPER_EXIT_OS
    finally:
        watchdog.set()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--elevated-service-action", choices=("start", "stop", "restart"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.elevated_service_action:
        return _run_elevated_service_action(args.elevated_service_action)
    if is_process_elevated():
        raise ConfigError("小票夹管理器界面不能以管理员身份运行；服务操作会按需单独请求 UAC 授权。")

    config = load_config()
    runtime = _build_runtime(config)
    controller = AppController(runtime, config)
    if config.runtime_mode == "source":
        controller.start()

    stop_event = threading.Event()
    threading.Thread(target=runtime.run_monitor, args=(stop_event,), daemon=True).start()

    token = secrets.token_urlsafe(24)
    server = ControlServer(
        config.manager_host,
        config.manager_port,
        controller=controller,
        token=token,
        ui_html=_UI_HTML,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    _open_app_window(config.manager_url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
