"""Stable UI projection and control adapter for Desktop Manager runtimes."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from types import MappingProxyType

from backend_manager.config import ConfigError, ManagerConfig
from backend_manager.desktop_shell import open_in_browser
from backend_manager.diagnostic_bundle import DiagnosticExportError, export_diagnostic_bundle
from backend_manager.netinfo import lan_ip
from backend_manager.projection import RuntimeConfigProvider, StaticRuntimeConfigProvider
from backend_manager.runtime import BackendRuntime, RuntimeControlError, RuntimeStatus

_OWNER_PATHS = MappingProxyType({
    "console": "",
    "pairing": "/pairing",
    "devices": "/devices",
    "upload_links": "/upload-links",
    "backups": "/backups",
    "diagnostics": "/diagnostics",
    "settings": "/settings",
})
_CONTROL_NOTICES = MappingProxyType({
    "start": "启动操作已完成。",
    "stop": "停止操作已完成。",
    "restart": "重启操作已完成。",
    "toggle_auto_restart": "自动重启设置已更新。",
})
_NOTICE_SECONDS = 8.0


class ManagerShuttingDownError(RuntimeError):
    """Raised when a new action races with an accepted maintenance handoff."""


class AppController:
    """Adapt one runtime into the stable JSON contract consumed by ``ui.html``."""

    def __init__(
        self,
        runtime_or_provider: BackendRuntime | RuntimeConfigProvider,
        config: ManagerConfig | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        maintenance_version: str | None = None,
        startup_failure_code: str | None = None,
        startup_failure_stage: str | None = None,
        request_shutdown: Callable[[], None] = lambda: None,
    ) -> None:
        self._provider = (
            StaticRuntimeConfigProvider(runtime_or_provider, config)
            if config is not None
            else runtime_or_provider
        )
        self._last_error: str | None = None
        self._last_notice: str | None = None
        self._last_notice_expires_at: float | None = None
        self._last_export_file: str | None = None
        self._monotonic = monotonic
        self._maintenance_version = maintenance_version or (
            config.expected_backend_version
            if config is not None and config.runtime_mode == "installed"
            else None
        )
        self._startup_failure_code = startup_failure_code
        self._startup_failure_stage = startup_failure_stage
        self._request_shutdown = request_shutdown
        self._manager_shutdown_requested = False
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
            last_error = self._last_error or status_error or snapshot.control_error
            if (
                self._last_notice_expires_at is not None
                and self._monotonic() >= self._last_notice_expires_at
            ):
                self._last_notice = None
                self._last_notice_expires_at = None
            last_notice = None if last_error else self._last_notice
            last_export_file = self._last_export_file
            manager_shutdown_requested = self._manager_shutdown_requested
        service_controls_available = (
            config is not None
            and status_error is None
            and snapshot.control_error is None
            and snapshot.backend_service_state not in {"missing", "unknown"}
            and snapshot.database_service_state not in {"missing", "unknown"}
        )
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
            "tunnel": None,
            "public_endpoint_state": snapshot.mobile_endpoint_state,
            "mobile_endpoint_state": snapshot.mobile_endpoint_state,
            "android_binding_state": snapshot.android_binding_state,
            "iphone_upload_state": snapshot.iphone_upload_state,
            "runtime_access_state": snapshot.runtime_access_state,
            "owner_state": snapshot.owner_state,
            "owner_recovery_channel": snapshot.owner_recovery_channel,
            "owner_url": config.owner_url if config is not None else None,
            "version": (
                config.expected_backend_version
                if config is not None and config.expected_backend_version
                else self._maintenance_version
            ),
            "startup_failure_code": self._startup_failure_code,
            "startup_failure_stage": self._startup_failure_stage,
            "service_controls_available": service_controls_available,
            "log": snapshot.log,
            "control_error": last_error,
            "action_notice": last_notice,
            "diagnostic_bundle_file": last_export_file,
            "manager_shutdown_requested": manager_shutdown_requested,
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
        self._open_owner_page("console")

    def open_pairing(self) -> None:
        self._open_owner_page("pairing")

    def open_devices(self) -> None:
        self._open_owner_page("devices")

    def open_upload_links(self) -> None:
        self._open_owner_page("upload_links")

    def open_backups(self) -> None:
        self._open_owner_page("backups")

    def open_diagnostics(self) -> None:
        self._open_owner_page("diagnostics")

    def open_settings(self) -> None:
        self._open_owner_page("settings")

    def export_diagnostics(self) -> None:
        self._begin_action()
        try:
            bundle = export_diagnostic_bundle(self.status())
        except DiagnosticExportError as exc:
            self._record_error(self._display_error(exc))
            return
        with self._lock:
            self._last_export_file = bundle.file_name
        self._record_notice("诊断包已保存到当前用户的下载文件夹。")

    def request_manager_shutdown(self) -> None:
        notify_host = False
        with self._lock:
            if not self._manager_shutdown_requested:
                self._manager_shutdown_requested = True
                notify_host = True
        if notify_host:
            self._request_shutdown()

    def is_manager_shutting_down(self) -> bool:
        with self._lock:
            return self._manager_shutdown_requested

    def _open_owner_page(self, destination: str) -> None:
        self._begin_action()
        try:
            projection = self._provider.current()
            config = projection.config
            snapshot = projection.runtime.status()
            if not snapshot.running or not snapshot.healthy or snapshot.health_state != "healthy":
                raise RuntimeControlError("后端身份尚未验证，任务页面没有打开；请先恢复服务。")
            if snapshot.runtime_access_state == "repair_required":
                raise RuntimeControlError("安装维护尚未完成；请关闭管理器并重新运行可信安装包。")
            if snapshot.owner_state == "recovery_required":
                raise RuntimeControlError(
                    "当前没有可用拥有者身份；管理器不能自动重建身份，请先导出诊断包。",
                )
            if destination == "pairing" and snapshot.android_binding_state != "configured_unverified":
                raise RuntimeControlError(
                    "电脑端运行正常，但尚未配置手机可达入口；请先在设置中完成连接配置。",
                )
            if destination == "upload_links" and snapshot.iphone_upload_state != "configured_unverified":
                raise RuntimeControlError(
                    "电脑端运行正常，但尚未配置 iPhone 上传入口；请先在设置中完成连接配置。",
                )
        except (ConfigError, RuntimeControlError) as exc:
            self._record_error(self._display_error(exc))
            return
        opened = open_in_browser(f"{config.owner_url}{_OWNER_PATHS[destination]}")
        if opened is False:
            self._record_error("无法打开系统浏览器，请检查 Windows 默认浏览器设置后重试。")
            return
        self._record_notice("任务页面已在浏览器中打开。")

    def _control(self, action_name: str) -> None:
        self._begin_action()
        try:
            runtime = self._provider.current().runtime
            getattr(runtime, action_name)()
        except (ConfigError, RuntimeControlError) as exc:
            self._record_error(self._display_error(exc))
        else:
            self._record_notice(_CONTROL_NOTICES[action_name])

    def _begin_action(self) -> None:
        with self._lock:
            if self._manager_shutdown_requested:
                raise ManagerShuttingDownError("小票夹管理器正在交接安装维护，已停止接收新操作。")
            self._last_error = None
            self._last_notice = None
            self._last_notice_expires_at = None

    def _record_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
            self._last_notice = None
            self._last_notice_expires_at = None

    def _record_notice(self, message: str) -> None:
        with self._lock:
            self._last_error = None
            self._last_notice = message
            self._last_notice_expires_at = self._monotonic() + _NOTICE_SECONDS

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
