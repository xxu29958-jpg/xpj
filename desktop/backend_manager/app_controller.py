"""Stable UI projection and control adapter for Desktop Manager runtimes."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import suppress
from types import MappingProxyType

from backend_manager.config import ConfigError, ManagerConfig
from backend_manager.desktop_shell import open_in_browser
from backend_manager.diagnostic_bundle import DiagnosticExportError, export_diagnostic_bundle
from backend_manager.netinfo import lan_ip
from backend_manager.product_data import (
    ProductDataError,
    activate_product_session,
    execute_inbox_command,
    fetch_product_workspace,
    list_product_ledgers,
    pair_product_session,
    revoke_product_session,
    switch_product_ledger,
)
from backend_manager.product_identity import (
    ProductCredentialError,
    ProductSession,
    delete_product_session,
    load_product_session,
    save_product_session,
)
from backend_manager.projection import RuntimeConfigProvider, StaticRuntimeConfigProvider
from backend_manager.runtime import BackendRuntime, RuntimeControlError, RuntimeStatus
from backend_manager.web_bff import BridgeContext

_OWNER_PATHS = MappingProxyType(
    {
        "console": "",
        "pairing": "/pairing",
        "devices": "/devices",
        "upload_links": "/upload-links",
        "backups": "/backups",
        "diagnostics": "/diagnostics",
        "settings": "/settings",
    }
)
_CONTROL_NOTICES = MappingProxyType(
    {
        "start": "启动操作已完成。",
        "stop": "停止操作已完成。",
        "restart": "重启操作已完成。",
        "toggle_auto_restart": "自动重启设置已更新。",
    }
)
_NOTICE_SECONDS = 8.0
_REBIND_RECOVERY_SUFFIX = ":desktop-rebind-recovery-v1"


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
        product_data_fetcher: Callable[..., dict] = fetch_product_workspace,
        product_ledger_fetcher: Callable[..., list[dict]] = list_product_ledgers,
        product_command_executor: Callable[..., dict] = execute_inbox_command,
        product_ledger_switcher: Callable[..., ProductSession] = switch_product_ledger,
        product_session_pairer: Callable[..., ProductSession] = pair_product_session,
        product_session_activator: Callable[..., ProductSession] = activate_product_session,
        product_session_revoker: Callable[..., None] = revoke_product_session,
        product_session_loader: Callable[[str], ProductSession | None] = load_product_session,
        product_session_saver: Callable[[str, ProductSession], None] = save_product_session,
        product_session_deleter: Callable[[str], None] = delete_product_session,
    ) -> None:
        self._provider = (
            StaticRuntimeConfigProvider(runtime_or_provider, config) if config is not None else runtime_or_provider
        )
        self._last_error: str | None = None
        self._last_notice: str | None = None
        self._last_notice_expires_at: float | None = None
        self._last_export_file: str | None = None
        self._monotonic = monotonic
        self._maintenance_version = maintenance_version or (
            config.expected_backend_version if config is not None and config.runtime_mode == "installed" else None
        )
        self._startup_failure_code = startup_failure_code
        self._startup_failure_stage = startup_failure_stage
        self._request_shutdown = request_shutdown
        self._product_data_fetcher = product_data_fetcher
        self._product_ledger_fetcher = product_ledger_fetcher
        self._product_command_executor = product_command_executor
        self._product_ledger_switcher = product_ledger_switcher
        self._product_session_pairer = product_session_pairer
        self._product_session_activator = product_session_activator
        self._product_session_revoker = product_session_revoker
        self._product_session_loader = product_session_loader
        self._product_session_saver = product_session_saver
        self._product_session_deleter = product_session_deleter
        self._manager_shutdown_requested = False
        self._lock = threading.RLock()
        self._product_session_lock = threading.RLock()

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
            if self._last_notice_expires_at is not None and self._monotonic() >= self._last_notice_expires_at:
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
        product_available = (
            config is not None
            and snapshot.running
            and snapshot.healthy
            and snapshot.health_state == "healthy"
            and snapshot.runtime_access_state == "available"
            and snapshot.owner_state == "configured"
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
            "product_url": f"{config.backend_origin}/web" if config is not None else None,
            "product_available": product_available,
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

    def product_workspace(self, workspace: str, ledger_id: str | None = None) -> dict:
        with self._product_session_lock:
            return self._product_workspace(workspace, ledger_id)

    def _product_workspace(self, workspace: str, ledger_id: str | None = None) -> dict:
        """Return one backend-owned projection under a paired app principal."""
        config = self._product_config(require_available=True)
        session = self._required_product_session(config)
        loopback_origin = f"http://127.0.0.1:{config.backend_port}"
        try:
            payload = self._product_data_fetcher(
                loopback_origin,
                workspace,
                ledger_id,
                session.session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
            ledgers = self._product_ledger_fetcher(
                loopback_origin,
                session.session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            self._clear_invalid_product_session(config, exc)
            raise
        if not any(row["ledger_id"] == session.ledger_id for row in ledgers):
            raise ProductDataError("当前绑定账本不在有效成员关系中。")
        return {
            **payload,
            "ledgers": [
                {
                    **row,
                    "is_current": row["ledger_id"] == session.ledger_id,
                }
                for row in ledgers
            ],
        }

    def product_inbox_command(
        self,
        public_id: str,
        ledger_id: str | None,
        payload: dict,
        idempotency_key: str,
    ) -> dict:
        with self._product_session_lock:
            return self._product_inbox_command(
                public_id,
                ledger_id,
                payload,
                idempotency_key,
            )

    def _product_inbox_command(
        self,
        public_id: str,
        ledger_id: str | None,
        payload: dict,
        idempotency_key: str,
    ) -> dict:
        """Forward one Inbox intent under the stored app principal."""
        config = self._product_config(require_available=True)
        session = self._required_product_session(config)
        loopback_origin = f"http://127.0.0.1:{config.backend_port}"
        try:
            return self._product_command_executor(
                loopback_origin,
                public_id,
                ledger_id,
                payload,
                idempotency_key,
                session.session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            self._clear_invalid_product_session(config, exc)
            raise

    def product_principal(self) -> dict:
        """Return only non-secret pairing metadata for the product UI."""

        with self._product_session_lock:
            config = self._product_config(require_available=False)
            session = self._load_product_session(config)
            loopback_origin = f"http://127.0.0.1:{config.backend_port}"
            session = self._reconcile_rebind_recovery(
                config,
                loopback_origin,
                session,
            )
            return session.public_projection() if session is not None else {"configured": False}

    def product_bridge_context(self) -> BridgeContext:
        """Return secrets only to the in-process Manager BFF."""
        with self._product_session_lock:
            config = self._product_config(require_available=True)
            session = self._required_product_session(config)
            return BridgeContext(
                backend_origin=f"http://127.0.0.1:{config.backend_port}",
                app_token=session.session_token,
            )

    def switch_product_principal_ledger(self, ledger_id: str) -> dict:
        with self._product_session_lock:
            return self._switch_product_principal_ledger(ledger_id)

    def _switch_product_principal_ledger(self, ledger_id: str) -> dict:
        """Rotate the app token, then atomically replace the WinCred session."""

        config = self._product_config(require_available=True)
        current = self._required_product_session(config)
        loopback_origin = f"http://127.0.0.1:{config.backend_port}"
        if ledger_id == current.ledger_id:
            return current.public_projection()
        try:
            replacement = self._product_ledger_switcher(
                loopback_origin,
                ledger_id,
                current.session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            self._clear_invalid_product_session(config, exc)
            raise
        if current.session_token == replacement.session_token:
            raise ProductDataError(
                "后端未轮换桌面身份，已保留原绑定。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        self._stage_rebind_recovery(config, replacement)
        activated = self._activate_and_promote_rebind(
            config,
            loopback_origin,
            replacement,
            current,
        )
        return activated.public_projection()

    def pair_product_principal(self, pairing_code: str) -> dict:
        with self._product_session_lock:
            return self._pair_product_principal(pairing_code)

    def _pair_product_principal(self, pairing_code: str) -> dict:
        """Replace the stored principal without orphaning the old app token."""

        config = self._product_config(require_available=True)
        loopback_origin = f"http://127.0.0.1:{config.backend_port}"
        current = self._load_product_session(config)
        current = self._reconcile_rebind_recovery(
            config,
            loopback_origin,
            current,
        )
        session = self._product_session_pairer(
            loopback_origin,
            pairing_code,
            timeout_seconds=config.health_request_timeout_seconds,
        )
        if current is not None and current.session_token == session.session_token:
            raise ProductDataError(
                "后端未轮换桌面身份，已保留原绑定。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        self._stage_rebind_recovery(config, session)
        activated = self._activate_and_promote_rebind(
            config,
            loopback_origin,
            session,
            current,
        )
        return activated.public_projection()

    def unpair_product_principal(self) -> dict:
        with self._product_session_lock:
            return self._unpair_product_principal()

    def _unpair_product_principal(self) -> dict:
        """Revoke the backend token, then remove the local WinCred entry."""

        config = self._product_config(require_available=False)
        session = self._load_product_session(config)
        loopback_origin = f"http://127.0.0.1:{config.backend_port}"
        session = self._reconcile_rebind_recovery(
            config,
            loopback_origin,
            session,
        )
        if session is None:
            return {"configured": False}
        try:
            self._product_session_revoker(
                loopback_origin,
                session.session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            if exc.status_code != 401:
                raise
        try:
            self._product_session_deleter(config.expected_installation_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc
        return {"configured": False}

    def _product_config(self, *, require_available: bool) -> ManagerConfig:
        if require_available and not self.status()["product_available"]:
            raise ProductDataError("小票夹服务尚未就绪，请先在系统管理中恢复服务。")
        try:
            return self._provider.current().config
        except (ConfigError, RuntimeControlError) as exc:
            raise ProductDataError(self._display_error(exc)) from exc

    def _load_product_session(self, config: ManagerConfig) -> ProductSession | None:
        return self._load_product_session_at(config.expected_installation_id)

    def _load_product_session_at(self, credential_id: str) -> ProductSession | None:
        try:
            return self._product_session_loader(credential_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    @staticmethod
    def _rebind_recovery_id(config: ManagerConfig) -> str:
        return f"{config.expected_installation_id}{_REBIND_RECOVERY_SUFFIX}"

    def _delete_rebind_recovery(self, config: ManagerConfig) -> None:
        try:
            self._product_session_deleter(self._rebind_recovery_id(config))
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    def _reconcile_rebind_recovery(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        current: ProductSession | None,
    ) -> ProductSession | None:
        recovery = self._load_product_session_at(self._rebind_recovery_id(config))
        if recovery is None:
            return current
        if current is not None and recovery.session_token == current.session_token:
            # Primary already contains B.  A duplicate recovery-slot cleanup
            # failure must not make the valid principal unusable; every later
            # reconciliation retries this idempotent cleanup.
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
            return current
        try:
            return self._activate_and_promote_rebind(
                config,
                loopback_origin,
                recovery,
                current,
            )
        except ProductDataError as exc:
            if exc.status_code == 401:
                # B expired/was revoked before activation.  Prepare never
                # displaced A.  Recovery cleanup is best-effort so a transient
                # WinCred delete failure cannot make that still-valid A
                # unusable; later calls retry the same cleanup.
                with suppress(ProductDataError):
                    self._delete_rebind_recovery(config)
                return current
            raise

    def _stage_rebind_recovery(
        self,
        config: ManagerConfig,
        session: ProductSession,
    ) -> None:
        try:
            self._product_session_saver(self._rebind_recovery_id(config), session)
        except ProductCredentialError as credential_error:
            raise self._credential_error(credential_error) from credential_error

    def _activate_and_promote_rebind(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        pending: ProductSession,
        current: ProductSession | None,
    ) -> ProductSession:
        try:
            activated = self._product_session_activator(
                loopback_origin,
                pending,
                current.session_token if current is not None else None,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            if exc.status_code == 401:
                raise
            raise ProductDataError(
                "新桌面身份仍安全保存在 Windows 凭据管理器中；恢复服务后会重放激活并完成切换。",
                error="product_rebind_recovery_pending",
                status_code=503,
            ) from exc
        if activated.session_token != pending.session_token:
            raise ProductDataError(
                "后端激活了未知桌面身份，恢复位已保留并停止提升。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        try:
            # Preserve the same raw B with its post-activation expiry metadata.
            self._product_session_saver(
                self._rebind_recovery_id(config),
                activated,
            )
            self._product_session_saver(
                config.expected_installation_id,
                activated,
            )
        except ProductCredentialError as exc:
            raise ProductDataError(
                "新桌面身份已激活且仍保存在恢复位；Windows 凭据管理器恢复后会自动提升为主身份。",
                error="product_rebind_recovery_pending",
                status_code=503,
            ) from exc
        # Primary B is durable at this point.  The recovery slot contains the
        # exact same bearer, so cleanup is best-effort and safely retryable.
        with suppress(ProductDataError):
            self._delete_rebind_recovery(config)
        return activated

    def _required_product_session(self, config: ManagerConfig) -> ProductSession:
        session = self._load_product_session(config)
        session = self._reconcile_rebind_recovery(
            config,
            f"http://127.0.0.1:{config.backend_port}",
            session,
        )
        if session is None:
            raise ProductDataError(
                "请先使用 8 位绑定码连接桌面账本。",
                error="product_principal_required",
                status_code=401,
            )
        return session

    def _clear_invalid_product_session(
        self,
        config: ManagerConfig,
        error: ProductDataError,
    ) -> None:
        if error.status_code != 401:
            return
        with suppress(ProductCredentialError):
            self._product_session_deleter(config.expected_installation_id)

    @staticmethod
    def _credential_error(error: ProductCredentialError) -> ProductDataError:
        return ProductDataError(
            str(error),
            error="product_credential_unavailable",
            status_code=503,
        )

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
