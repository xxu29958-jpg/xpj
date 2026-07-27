"""Stable UI projection and control adapter for Desktop Manager runtimes."""

from __future__ import annotations

import secrets
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
    PendingProductSession,
    ProductDataError,
    activate_product_session,
    derive_desktop_pending_token,
    list_product_ledgers,
    new_activation_attempt,
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
from backend_manager.product_recovery import (
    RebindRecovery,
    delete_rebind_recovery,
    load_rebind_recovery,
    save_rebind_recovery,
)
from backend_manager.projection import RuntimeConfigProvider, StaticRuntimeConfigProvider
from backend_manager.runtime import BackendRuntime, RuntimeControlError, RuntimeStatus
from backend_manager.web_bff import BridgeContext

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


# Attempt-level terminal answers: the ceremony cannot be replayed, so the
# provisional record must go (distinct from a mere wrong-code rejection).
_TERMINAL_ATTEMPT_ERRORS = frozenset({"pairing_attempt_expired", "pairing_attempt_closed"})


def _snapshot_product_available(snapshot: RuntimeStatus) -> bool:
    """Runtime readiness for the BFF surface (pairing state is NOT included)."""
    return (
        snapshot.running
        and snapshot.healthy
        and snapshot.health_state == "healthy"
        and snapshot.runtime_access_state == "available"
        and snapshot.owner_state == "configured"
    )


def _recovery_from_pending(
    pending: PendingProductSession,
    *,
    superseded_session_token: str | None = None,
) -> RebindRecovery:
    """Persist the client-owned attempt proof plus staged display metadata.

    ``superseded_session_token`` is the cross-ledger credential the ceremony
    replaces: activation cannot retire it (the backend only accepts
    same-ledger predecessors), so it rides along until the post-promotion
    revoke succeeds — a retryable cleanup record, response-loss safe.
    """
    return RebindRecovery(
        activation_attempt_id=pending.activation_attempt_id,
        activation_attempt_secret=pending.activation_attempt_secret,
        account_name=pending.session.account_name,
        ledger_id=pending.session.ledger_id,
        ledger_name=pending.session.ledger_name,
        device_name=pending.session.device_name,
        role=pending.session.role,
        activation_expires_at=pending.session.expires_at,
        superseded_session_token=superseded_session_token,
    )


def _pending_from_recovery(recovery: RebindRecovery) -> PendingProductSession:
    """Rebuild the staged session from the durable proof (never a stored token)."""
    return PendingProductSession(
        activation_attempt_id=recovery.activation_attempt_id,
        activation_attempt_secret=recovery.activation_attempt_secret,
        session=ProductSession(
            session_token=derive_desktop_pending_token(
                recovery.activation_attempt_secret,
                recovery.activation_attempt_id,
            ),
            account_name=recovery.account_name,
            ledger_id=recovery.ledger_id,
            ledger_name=recovery.ledger_name,
            device_name=recovery.device_name,
            role=recovery.role,
            expires_at=recovery.activation_expires_at,
        ),
    )


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
        product_session_pairer: Callable[..., PendingProductSession] = pair_product_session,
        product_ledger_switcher: Callable[..., PendingProductSession] = switch_product_ledger,
        product_session_activator: Callable[..., ProductSession] = activate_product_session,
        product_session_revoker: Callable[..., None] = revoke_product_session,
        product_ledger_fetcher: Callable[..., list[dict]] = list_product_ledgers,
        product_session_loader: Callable[[str], ProductSession | None] = load_product_session,
        product_session_saver: Callable[[str, ProductSession], None] = save_product_session,
        product_session_deleter: Callable[[str], None] = delete_product_session,
        product_recovery_loader: Callable[[str], RebindRecovery | None] = load_rebind_recovery,
        product_recovery_saver: Callable[[str, RebindRecovery], None] = save_rebind_recovery,
        product_recovery_deleter: Callable[[str], None] = delete_rebind_recovery,
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
        self._product_session_pairer = product_session_pairer
        self._product_ledger_switcher = product_ledger_switcher
        self._product_session_activator = product_session_activator
        self._product_session_revoker = product_session_revoker
        self._product_ledger_fetcher = product_ledger_fetcher
        self._product_session_loader = product_session_loader
        self._product_session_saver = product_session_saver
        self._product_session_deleter = product_session_deleter
        self._product_recovery_loader = product_recovery_loader
        self._product_recovery_saver = product_recovery_saver
        self._product_recovery_deleter = product_recovery_deleter
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
        product_available = config is not None and _snapshot_product_available(snapshot)
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
            # The manager-relative BFF entry. Availability tracks runtime
            # readiness only; pairing state lives in /api/product/session.
            "product_url": "/web" if product_available else None,
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

    def stop(self) -> None:
        self._control("stop")

    def restart(self) -> None:
        self._control("restart")

    def auto_restart(self) -> None:
        self._control("toggle_auto_restart")

    def product_principal(self) -> dict:
        """Return only non-secret pairing metadata for the product UI."""

        with self._product_session_lock:
            config = self._product_config(require_available=False)
            session = self._load_product_session(config)
            session = self._reconcile_rebind_recovery(
                config,
                self._loopback_origin(config),
                session,
            )
            return session.public_projection() if session is not None else {"configured": False}

    def product_bridge_context(self) -> BridgeContext:
        """Return secrets only to the in-process Manager BFF."""
        with self._product_session_lock:
            config = self._product_config(require_available=True)
            session = self._required_product_session(config)
            return BridgeContext(
                backend_origin=self._loopback_origin(config),
                app_token=session.session_token,
            )

    def note_product_bridge_auth_failure(self, status_code: int, failed_token: str) -> bool:
        """A bridged product request was rejected: retire exactly that credential.

        The BFF relays backend responses verbatim, so this hook is the only
        place a 401 from the product surface can retire the stored token.
        Deletion is conditional on the failed token still being the stored
        one: a request that raced a ledger switch may carry the already
        superseded credential — the fresh session must not be wiped with it.
        Returns True only when the stored credential was actually cleared
        (drives whether the bridge renders the rebind recovery page).
        """
        if status_code != 401:
            return False
        with self._product_session_lock:
            config = self._product_config(require_available=False)
            session = self._load_product_session(config)
            if session is None or not secrets.compare_digest(
                session.session_token,
                failed_token,
            ):
                return False
            with suppress(ProductCredentialError):
                self._product_session_deleter(config.expected_installation_id)
            # The replacement just died while a superseded revoke was still
            # owed: attempt it here (best-effort) rather than letting the old
            # credential live to TTL with no client reference left. The
            # recovery record itself stays — reconcile owns its lifecycle,
            # and it may still hold an uncommitted ceremony.
            recovery = self._load_rebind_recovery(config)
            if recovery is not None and recovery.superseded_session_token:
                self._revoke_superseded_session(
                    config,
                    self._loopback_origin(config),
                    recovery.superseded_session_token,
                )
        return True

    def product_ledgers(self) -> list[dict]:
        """List the paired account's memberships for the manager switch UI."""

        with self._product_session_lock:
            config = self._product_config(require_available=True)
            session = self._required_product_session(config)
            try:
                rows = self._product_ledger_fetcher(
                    self._loopback_origin(config),
                    session.session_token,
                    timeout_seconds=config.health_request_timeout_seconds,
                )
            except ProductDataError as exc:
                self._clear_invalid_product_session(config, exc)
                raise
            return [
                {
                    **row,
                    "is_current": row["ledger_id"] == session.ledger_id,
                }
                for row in rows
            ]

    def pair_product_principal(self, pairing_code: str) -> dict:
        with self._product_session_lock:
            self._begin_action()
            return self._pair_product_principal(pairing_code)

    def _pair_product_principal(self, pairing_code: str) -> dict:
        """Stage, activate, then atomically replace the WinCred principal."""

        config = self._product_config(require_available=True)
        loopback_origin = self._loopback_origin(config)
        current = self._load_product_session(config)
        current = self._reconcile_rebind_recovery(
            config,
            loopback_origin,
            current,
        )
        # Persist the attempt proof BEFORE the pairing code is consumed: a
        # response loss or process death after the backend commits would
        # otherwise orphan the staged credential forever ( the one-time code
        # rejects any fresh attempt). A retry reuses the exact same proof.
        # But never overwrite a completed ceremony whose superseded revoke is
        # still owed: settle that duty first (same semantics as unpair —
        # transient failure refuses to start the new pair and keeps the record).
        existing = self._load_rebind_recovery(config)
        if existing is not None and existing.ledger_id:
            if existing.superseded_session_token and not self._revoke_superseded_session(
                config,
                loopback_origin,
                existing.superseded_session_token,
            ):
                raise ProductDataError(
                    "旧凭据尚未完成清理，请稍后重试绑定。",
                    error="product_cleanup_pending",
                    status_code=503,
                )
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
        provisional = self._load_rebind_recovery(config)
        if provisional is not None and not provisional.ledger_id:
            attempt = (
                provisional.activation_attempt_id,
                provisional.activation_attempt_secret,
            )
            attempt_is_fresh = False
        else:
            attempt = new_activation_attempt()
            attempt_is_fresh = True
            self._stage_rebind_recovery(
                config,
                RebindRecovery(
                    activation_attempt_id=attempt[0],
                    activation_attempt_secret=attempt[1],
                ),
            )
        try:
            pending = self._product_session_pairer(
                loopback_origin,
                pairing_code,
                attempt=attempt,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            if exc.error in _TERMINAL_ATTEMPT_ERRORS:
                # The ceremony is terminally over (code TTL / closed): the proof
                # has no replay value — drop it so the next pair starts fresh
                # instead of retrying the same dead attempt forever.
                with suppress(ProductDataError):
                    self._delete_rebind_recovery(config)
            elif exc.error == "invalid_pairing_code" and attempt_is_fresh:
                # A proof minted in THIS call could never have committed, so
                # the rejected code really left nothing behind — drop it. A
                # reused provisional whose code was rejected is NOT cleared:
                # that 401 is a proof/code mismatch on a possibly committed
                # ceremony, which only the original code (or unpair/TTL)
                # resolves honestly.
                with suppress(ProductDataError):
                    self._delete_rebind_recovery(config)
            raise
        if current is not None and secrets.compare_digest(
            current.session_token,
            pending.session.session_token,
        ):
            # Deliberate abandonment: the staged server credential dies by
            # TTL; nothing client-side should replay this ceremony later.
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
            raise ProductDataError(
                "后端未轮换桌面身份，已保留原绑定。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        recovery = _recovery_from_pending(
            pending,
            superseded_session_token=(
                current.session_token
                if current is not None and current.ledger_id != pending.session.ledger_id
                else None
            ),
        )
        self._stage_rebind_recovery(config, recovery)
        activated = self._activate_and_promote_rebind(
            config,
            loopback_origin,
            recovery,
            current,
        )
        return activated.public_projection()

    def unpair_product_principal(self) -> dict:
        with self._product_session_lock:
            self._begin_action()
            return self._unpair_product_principal()

    def _unpair_product_principal(self) -> dict:
        """Revoke the backend token(s), then remove the local WinCred entries.

        Owed cleanup settles BEFORE teardown: when a superseded revoke fails
        transiently, unpair refuses to complete (the cleanup record stays
        retryable) instead of reporting success while a credential is orphaned.
        """

        config = self._product_config(require_available=False)
        loopback_origin = self._loopback_origin(config)
        session = self._load_product_session(config)
        session = self._reconcile_rebind_recovery(
            config,
            loopback_origin,
            session,
        )
        # A recovery record can outlive the primary — an in-flight ceremony
        # and/or an owed superseded revoke. Unpair only starts teardown once
        # the owed revoke is durably done; a transient failure keeps
        # everything in place for the next attempt.
        recovery = self._load_rebind_recovery(config)
        if recovery is not None:
            if recovery.superseded_session_token and not self._revoke_superseded_session(
                config,
                loopback_origin,
                recovery.superseded_session_token,
            ):
                raise ProductDataError(
                    "旧凭据尚未完成清理，请稍后重试解除绑定。",
                    error="product_cleanup_pending",
                    status_code=503,
                )
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
        if session is not None:
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

    def switch_product_principal_ledger(self, ledger_id: str) -> dict:
        with self._product_session_lock:
            self._begin_action()
            return self._switch_product_principal_ledger(ledger_id)

    def _switch_product_principal_ledger(self, ledger_id: str) -> dict:
        """Two-phase switch: stage on the target, activate, then retire the old."""

        config = self._product_config(require_available=True)
        loopback_origin = self._loopback_origin(config)
        current = self._required_product_session(config)
        if ledger_id == current.ledger_id:
            return current.public_projection()
        try:
            pending = self._product_ledger_switcher(
                loopback_origin,
                ledger_id,
                current.session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            self._clear_invalid_product_session(config, exc)
            raise
        if secrets.compare_digest(current.session_token, pending.session.session_token):
            raise ProductDataError(
                "后端未轮换桌面身份，已保留原绑定。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        recovery = _recovery_from_pending(
            pending,
            superseded_session_token=current.session_token,
        )
        self._stage_rebind_recovery(config, recovery)
        activated = self._activate_and_promote_rebind(
            config,
            loopback_origin,
            recovery,
            current,
        )
        return activated.public_projection()

    def _product_config(self, *, require_available: bool) -> ManagerConfig:
        if require_available and not self._product_available():
            raise ProductDataError("小票夹服务尚未就绪，请先在系统管理中恢复服务。")
        try:
            return self._provider.current().config
        except (ConfigError, RuntimeControlError) as exc:
            raise ProductDataError(self._display_error(exc)) from exc

    def _product_available(self) -> bool:
        try:
            snapshot = self._provider.current().runtime.status()
        except (ConfigError, RuntimeControlError):
            return False
        return _snapshot_product_available(snapshot)

    @staticmethod
    def _loopback_origin(config: ManagerConfig) -> str:
        return f"http://127.0.0.1:{config.backend_port}"

    def _load_product_session(self, config: ManagerConfig) -> ProductSession | None:
        try:
            return self._product_session_loader(config.expected_installation_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    def _load_rebind_recovery(self, config: ManagerConfig) -> RebindRecovery | None:
        try:
            return self._product_recovery_loader(config.expected_installation_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    def _stage_rebind_recovery(
        self,
        config: ManagerConfig,
        recovery: RebindRecovery,
    ) -> None:
        try:
            self._product_recovery_saver(config.expected_installation_id, recovery)
        except ProductCredentialError as credential_error:
            raise self._credential_error(credential_error) from credential_error

    def _delete_rebind_recovery(self, config: ManagerConfig) -> None:
        try:
            self._product_recovery_deleter(config.expected_installation_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    def _reconcile_rebind_recovery(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        current: ProductSession | None,
    ) -> ProductSession | None:
        recovery = self._load_rebind_recovery(config)
        if recovery is None:
            return current
        if not recovery.ledger_id:
            # Provisional pair attempt (persisted before the pairing code was
            # consumed): only an explicit pair() call completes it — a passive
            # status read must never spend the proof.
            return current
        if not self._product_available():
            # The backend on the configured port is not identity-verified
            # right now (degraded, mismatched, or simply down). Replaying the
            # activation proof against whatever answers there could burn it:
            # a foreign/stale instance's 401 would be mistaken for an expired
            # attempt and the record deleted. Render the cached non-secret
            # session and retry the replay once the runtime is verified.
            return current
        derived = derive_desktop_pending_token(
            recovery.activation_attempt_secret,
            recovery.activation_attempt_id,
        )
        if current is not None and secrets.compare_digest(derived, current.session_token):
            # Primary already contains B. A retained superseded token means
            # the post-promotion revoke is still owed — retry it now; only a
            # durable cleanup (or a dead predecessor) drops the record.
            if recovery.superseded_session_token and not self._revoke_superseded_session(
                config,
                loopback_origin,
                recovery.superseded_session_token,
            ):
                return current
            # Duplicate recovery-slot cleanup failure must not make the valid
            # principal unusable; every later reconciliation retries it.
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
                # The staged attempt expired/was revoked before activation, and
                # prepare never displaced A. Hard gate: never revoke the token
                # that is still the live primary — when the failed ceremony's
                # superseded equals the current session, A was never displaced
                # and stays the user's identity. Only a genuinely orphaned
                # superseded (primary promoted past it, or already gone) may be
                # revoked here. A transient (non-death) revoke failure keeps
                # the record so a later reconcile retries; the record drops
                # only once the owed revoke succeeded or the token was dead.
                owed = recovery.superseded_session_token
                owed_settled = True
                if owed and (
                    current is None
                    or not secrets.compare_digest(current.session_token, owed)
                ):
                    owed_settled = self._revoke_superseded_session(
                        config,
                        loopback_origin,
                        owed,
                    )
                if owed_settled:
                    with suppress(ProductDataError):
                        self._delete_rebind_recovery(config)
                return current
            raise

    def _activate_and_promote_rebind(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        recovery: RebindRecovery,
        current: ProductSession | None,
    ) -> ProductSession:
        # Only a same-ledger re-pair may prove the predecessor: the backend
        # binds X-Ticketbox-Previous-Session to the staged account AND ledger,
        # so a switch (cross-ledger) must never send it.
        previous = (
            current.session_token
            if current is not None and current.ledger_id == recovery.ledger_id
            else None
        )
        try:
            activated = self._product_session_activator(
                loopback_origin,
                _pending_from_recovery(recovery),
                previous,
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
        expected = derive_desktop_pending_token(
            recovery.activation_attempt_secret,
            recovery.activation_attempt_id,
        )
        if not secrets.compare_digest(activated.session_token, expected):
            raise ProductDataError(
                "后端激活了未知桌面身份，恢复位已保留并停止提升。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        try:
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
        # Primary B is durable at this point. A cross-ledger predecessor is
        # never a valid activation proof, so it must be revoked client-side:
        # if that revoke fails we deliberately keep the recovery record as a
        # retryable cleanup marker instead of silently leaking the old token.
        if recovery.superseded_session_token and not self._revoke_superseded_session(
            config,
            loopback_origin,
            recovery.superseded_session_token,
        ):
            return activated
        # The recovery slot holds the same ceremony's proof, so cleanup is
        # best-effort and safely retryable.
        with suppress(ProductDataError):
            self._delete_rebind_recovery(config)
        return activated

    def _revoke_superseded_session(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        session_token: str,
    ) -> bool:
        """Retire one superseded credential. True when it is gone (revoked now
        or already dead); False when a later reconcile must retry."""
        try:
            self._product_session_revoker(
                loopback_origin,
                session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
            return True
        except ProductDataError as exc:
            return exc.status_code == 401

    def _required_product_session(self, config: ManagerConfig) -> ProductSession:
        session = self._load_product_session(config)
        session = self._reconcile_rebind_recovery(
            config,
            self._loopback_origin(config),
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
