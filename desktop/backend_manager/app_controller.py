"""Stable UI projection and control adapter for Desktop Manager runtimes."""

from __future__ import annotations

import threading

from backend_manager.config import ConfigError, ManagerConfig
from backend_manager.desktop_shell import open_in_browser
from backend_manager.netinfo import lan_ip
from backend_manager.projection import RuntimeConfigProvider, StaticRuntimeConfigProvider
from backend_manager.runtime import BackendRuntime, RuntimeControlError, RuntimeStatus


class AppController:
    """Adapt one runtime into the stable JSON contract consumed by ``ui.html``."""

    def __init__(
        self,
        runtime_or_provider: BackendRuntime | RuntimeConfigProvider,
        config: ManagerConfig | None = None,
    ) -> None:
        self._provider = (
            StaticRuntimeConfigProvider(runtime_or_provider, config)
            if config is not None
            else runtime_or_provider
        )
        self._last_error: str | None = None
        self._lock = threading.RLock()

    def status(self) -> dict:
        status_error: str | None = None
        config: ManagerConfig | None = None
        try:
            projection = self._provider.current()
            config = projection.config
            snapshot = projection.runtime.status()
        except (ConfigError, RuntimeControlError) as exc:
            status_error = self._display_error(exc)
            snapshot = self._unavailable_status()
        ip = lan_ip()
        port = config.backend_port if config is not None else None
        lan_endpoint = config.lan_endpoint(ip) if config is not None else None
        if config is None:
            lan_text = "安装信息不可用" if self._provider.mode_hint == "installed" else "运行配置不可用"
        elif lan_endpoint:
            lan_text = lan_endpoint
        elif config.lan_endpoint("127.0.0.1") is None:
            lan_text = "仅本机监听"
        else:
            lan_text = "未发现局域网地址"
        with self._lock:
            last_error = status_error or snapshot.control_error or self._last_error
        return {
            "runtime_mode": snapshot.mode,
            "running": snapshot.running,
            "health": snapshot.healthy,
            "health_state": snapshot.health_state,
            "health_detail": snapshot.health_detail,
            "uptime_seconds": snapshot.uptime_seconds,
            "pid": snapshot.pid,
            "port": port,
            "auto_restart": snapshot.auto_restart,
            "auto_restart_configurable": snapshot.auto_restart_configurable,
            "restarts": snapshot.restarts,
            "backend_service_state": snapshot.backend_service_state,
            "database_service_state": snapshot.database_service_state,
            "lan": lan_text,
            "tunnel": config.public_base_url if config is not None else None,
            "public_endpoint_state": config.public_endpoint_state if config is not None else "unknown",
            "owner_url": config.owner_url if config is not None else None,
            "log": snapshot.log,
            "control_error": last_error,
        }

    def start(self) -> None:
        self._control("start")

    def stop(self) -> None:
        self._control("stop")

    def restart(self) -> None:
        self._control("restart")

    def auto_restart(self) -> None:
        self._control("toggle_auto_restart")

    def open_console(self) -> None:
        try:
            config = self._provider.current().config
        except (ConfigError, RuntimeControlError) as exc:
            with self._lock:
                self._last_error = self._display_error(exc)
            return
        open_in_browser(config.owner_url)

    def _control(self, action_name: str) -> None:
        try:
            runtime = self._provider.current().runtime
            getattr(runtime, action_name)()
        except (ConfigError, RuntimeControlError) as exc:
            with self._lock:
                self._last_error = self._display_error(exc)
        else:
            with self._lock:
                self._last_error = None

    def _unavailable_status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode=self._provider.mode_hint,
            running=False,
            healthy=False,
            pid=None,
            uptime_seconds=0,
            auto_restart=self._provider.mode_hint == "installed",
            auto_restart_configurable=self._provider.mode_hint == "source",
            restarts=0,
            backend_service_state="unknown" if self._provider.mode_hint == "installed" else None,
            database_service_state="unknown" if self._provider.mode_hint == "installed" else None,
            log=["运行投影不可用；未使用启动时的旧安装信息。"],
            control_error=None,
            health_state="pending",
            health_detail="无法读取 Ticketbox 运行状态。",
        )

    def _display_error(self, exc: Exception) -> str:
        if self._provider.mode_hint == "installed" and isinstance(exc, ConfigError):
            return "安装信息已变化或不可用；请等待升级完成，或修复/重新安装小票夹。"
        return str(exc)
