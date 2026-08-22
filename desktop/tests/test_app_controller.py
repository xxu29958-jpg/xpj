"""Stable UI status contract and user-visible control failures."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend_manager.app_controller import AppController, ManagerShuttingDownError
from backend_manager.config import ConfigError, InstalledRuntimeConfig, ManagerConfig, SourceRuntimeConfig
from backend_manager.diagnostic_bundle import DiagnosticBundle
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.projection import (
    RefreshingInstalledRuntimeConfigProvider,
    UnavailableInstalledRuntimeConfigProvider,
)
from backend_manager.runtime import RuntimeControlError, RuntimeStatus


class FakeRuntime:
    def __init__(self) -> None:
        self.fail_start = False

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode="source",
            running=True,
            healthy=True,
            pid=123,
            uptime_seconds=45,
            auto_restart=True,
            auto_restart_configurable=True,
            restarts=2,
            backend_service_state=None,
            database_service_state=None,
            log=["ready"],
            health_state="healthy",
            health_detail="identity verified",
            mobile_endpoint_state="public_configured_unverified",
            android_binding_state="configured_unverified",
            iphone_upload_state="configured_unverified",
            runtime_access_state="available",
            owner_state="configured",
            owner_recovery_channel="managed_host",
        )

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeControlError("需要管理员权限")

    def stop(self) -> None:
        pass

    def restart(self) -> None:
        pass

    def toggle_auto_restart(self) -> bool:
        return True

    def run_monitor(self, _stop_event) -> None:
        pass


def _config() -> ManagerConfig:
    return ManagerConfig(
        runtime=SourceRuntimeConfig(Path("backend"), Path("python.exe"), Path("backend")),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=None,
        expected_installation_id="ticketbox-0123456789abcdef0123456789abcdef",
        health_request_timeout_seconds=3.0,
    )


def test_status_exposes_runtime_capabilities(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.app_controller.lan_ip", lambda: "192.168.1.8")
    controller = AppController(FakeRuntime(), _config())

    status = controller.status()

    assert status["runtime_mode"] == "source"
    assert status["auto_restart_configurable"] is True
    assert status["lan"] == "仅本机监听"
    assert status["control_error"] is None
    assert status["health_state"] == "healthy"
    assert status["health_detail"] == "identity verified"
    assert status["mobile_endpoint_state"] == "public_configured_unverified"
    assert status["android_binding_state"] == "configured_unverified"
    assert status["runtime_access_state"] == "available"


def test_control_failure_is_returned_then_cleared_after_success() -> None:
    runtime = FakeRuntime()
    controller = AppController(runtime, _config())
    runtime.fail_start = True

    controller.start()
    assert controller.status()["control_error"] == "需要管理员权限"

    runtime.fail_start = False
    controller.start()
    assert controller.status()["control_error"] is None
    assert controller.status()["action_notice"] == "启动操作已完成。"

    runtime.fail_start = True
    controller.start()
    failed = controller.status()
    assert failed["control_error"] == "需要管理员权限"
    assert failed["action_notice"] is None


def test_success_notice_expires_without_clearing_persistent_task_result() -> None:
    now = [100.0]
    controller = AppController(FakeRuntime(), _config(), monotonic=lambda: now[0])

    controller.start()
    assert controller.status()["action_notice"] == "启动操作已完成。"

    now[0] += 9.0
    status = controller.status()
    assert status["action_notice"] is None


def test_task_links_open_exact_owner_authority_pages(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(FakeRuntime(), _config())

    controller.open_pairing()
    controller.open_devices()
    controller.open_upload_links()
    controller.open_backups()
    controller.open_diagnostics()
    controller.open_settings()

    assert opened == [
        "http://127.0.0.1:8000/owner/pairing",
        "http://127.0.0.1:8000/owner/devices",
        "http://127.0.0.1:8000/owner/upload-links",
        "http://127.0.0.1:8000/owner/backups",
        "http://127.0.0.1:8000/owner/diagnostics",
        "http://127.0.0.1:8000/owner/settings",
    ]
    assert controller.status()["action_notice"] == "任务页面已在浏览器中打开。"


def test_task_link_browser_failure_is_actionable(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", lambda _url: False)
    controller = AppController(FakeRuntime(), _config())

    controller.open_pairing()

    assert controller.status()["control_error"] == (
        "无法打开系统浏览器，请检查 Windows 默认浏览器设置后重试。"
    )


def test_local_pairing_stays_available_while_mobile_upload_tasks_fail_closed(monkeypatch) -> None:
    opened: list[str] = []

    class LocalOnlyRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(
                **{
                    **snapshot.__dict__,
                    "mobile_endpoint_state": "local_only",
                    "android_binding_state": "setup_required",
                    "iphone_upload_state": "setup_required",
                },
            )

    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(LocalOnlyRuntime(), _config())

    controller.open_pairing()
    assert opened == ["http://127.0.0.1:8000/owner/pairing"]
    controller.open_upload_links()
    assert "尚未配置 iPhone 上传入口" in controller.status()["control_error"]
    assert opened == ["http://127.0.0.1:8000/owner/pairing"]


def test_task_link_revalidates_backend_identity_before_opening(monkeypatch) -> None:
    opened: list[str] = []

    class MismatchedRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(
                **{
                    **snapshot.__dict__,
                    "healthy": False,
                    "health_state": "mismatch",
                    "health_detail": "foreign listener",
                },
            )

    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(MismatchedRuntime(), _config())

    controller.open_pairing()

    assert opened == []
    assert "身份尚未验证" in controller.status()["control_error"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("runtime_access_state", "repair_required", "安装维护尚未完成"),
        ("owner_state", "recovery_required", "不能自动重建身份"),
    ],
)
def test_owner_tasks_fail_closed_for_distinct_recovery_states(
    monkeypatch,
    field: str,
    value: str,
    message: str,
) -> None:
    opened: list[str] = []

    class RecoveryRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(**{**snapshot.__dict__, field: value})

    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(RecoveryRuntime(), _config())

    controller.open_console()

    assert opened == []
    assert message in controller.status()["control_error"]


def test_diagnostic_export_exposes_only_file_name_and_human_notice(monkeypatch, tmp_path) -> None:
    bundle = DiagnosticBundle(tmp_path / "Ticketbox-Diagnostics-20260713-000000Z.zip")
    monkeypatch.setattr("backend_manager.app_controller.export_diagnostic_bundle", lambda _status: bundle)
    controller = AppController(FakeRuntime(), _config())

    controller.export_diagnostics()
    status = controller.status()

    assert status["diagnostic_bundle_file"] == bundle.file_name
    assert status["action_notice"] == "诊断包已保存到当前用户的下载文件夹。"
    assert str(tmp_path) not in str(status)


def _installed_config(tmp_path: Path, *, port: int, service_suffix: str) -> ManagerConfig:
    layout = InstalledLayout(
        install_dir=tmp_path / f"program-{service_suffix}",
        data_root=tmp_path / f"data-{service_suffix}",
        backend_port=port,
        pg_port=5432,
        backend_service_name=f"TicketboxBackend{service_suffix}",
        pg_service_name=f"TicketboxPg{service_suffix}",
        backend_version=f"1.0.{port}",
    )
    release = WindowsReleaseConfig(
        backend_service_name=layout.backend_service_name,
        pg_service_name=layout.pg_service_name,
        service_state_timeout_ms=10_000,
        service_poll_interval_ms=100,
        postgres_ready_timeout_ms=20_000,
        backend_ready_timeout_ms=30_000,
        backend_ready_poll_interval_ms=200,
        backend_health_request_timeout_ms=1_000,
        database_tool_timeout_ms=600_000,
        complete_dataset_backup_timeout_ms=1_800_000,
        complete_dataset_restore_timeout_ms=3_600_000,
    )
    return ManagerConfig(
        runtime=InstalledRuntimeConfig(layout, release),
        backend_host="127.0.0.1",
        backend_port=port,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=layout.backend_version,
        expected_installation_id=layout.installation_id,
        health_request_timeout_seconds=1.0,
    )


def test_installed_controller_refreshes_projection_for_status_action_and_console(monkeypatch, tmp_path: Path) -> None:
    configs = [
        _installed_config(tmp_path, port=8101, service_suffix="Old"),
        _installed_config(tmp_path, port=8202, service_suffix="New"),
        _installed_config(tmp_path, port=8404, service_suffix="Action"),
        _installed_config(tmp_path, port=8303, service_suffix="Console"),
    ]
    actions: list[tuple[str, int]] = []

    class Runtime(FakeRuntime):
        def __init__(self, config: ManagerConfig) -> None:
            super().__init__()
            self._config = config

        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(**{**snapshot.__dict__, "mode": "installed"})

        def start(self) -> None:
            actions.append((self._config.runtime.backend_service_name, self._config.backend_port))

    provider = RefreshingInstalledRuntimeConfigProvider(
        config_loader=lambda: configs.pop(0),
        runtime_builder=Runtime,
    )
    opened: list[str] = []
    monkeypatch.setattr("backend_manager.app_controller.open_in_browser", opened.append)
    controller = AppController(provider)

    assert controller.status()["port"] == 8101
    assert controller.status()["public_endpoint_state"] == "public_configured_unverified"
    controller.start()
    controller.open_console()

    assert actions == [("TicketboxBackendAction", 8404)]
    assert opened == ["http://127.0.0.1:8303/owner"]


def test_installed_refresh_failure_does_not_reuse_stale_projection(tmp_path: Path) -> None:
    calls = 0
    config = _installed_config(tmp_path, port=8101, service_suffix="Old")

    def load() -> ManagerConfig:
        nonlocal calls
        calls += 1
        if calls == 1:
            return config
        raise ConfigError(r"secret path C:\ProgramData\Ticketbox\app\.env")

    provider = RefreshingInstalledRuntimeConfigProvider(config_loader=load, runtime_builder=lambda _config: FakeRuntime())
    controller = AppController(provider)

    assert controller.status()["port"] == 8101
    unavailable = controller.status()
    controller.start()

    assert unavailable["port"] is None
    assert unavailable["owner_url"] is None
    assert "ProgramData" not in unavailable["control_error"]
    assert "安装信息已变化或不可用" in unavailable["control_error"]


def test_installed_monitor_reloads_projection_on_each_tick(tmp_path: Path) -> None:
    stop_event = threading.Event()
    ports: list[int] = []
    configs = iter(
        [
            _installed_config(tmp_path, port=8101, service_suffix="One"),
            _installed_config(tmp_path, port=8202, service_suffix="Two"),
        ],
    )

    class Runtime(FakeRuntime):
        def __init__(self, config: ManagerConfig) -> None:
            super().__init__()
            self._config = config

        def status(self) -> RuntimeStatus:
            ports.append(self._config.backend_port)
            if len(ports) == 2:
                stop_event.set()
            return super().status()

    provider = RefreshingInstalledRuntimeConfigProvider(
        config_loader=lambda: next(configs),
        runtime_builder=Runtime,
        monitor_seconds=0.001,
    )

    provider.run_monitor(stop_event)

    assert ports == [8101, 8202]


def test_shutdown_seal_is_idempotent_and_rejects_direct_actions() -> None:
    shutdown_requests: list[str] = []
    controller = AppController(
        UnavailableInstalledRuntimeConfigProvider(),
        maintenance_version="1.2.0",
        startup_failure_code="release_contract_invalid",
        startup_failure_stage="runtime_discovery",
        request_shutdown=lambda: shutdown_requests.append("shutdown"),
    )

    controller.request_manager_shutdown()
    controller.request_manager_shutdown()

    assert controller.is_manager_shutting_down() is True
    assert shutdown_requests == ["shutdown"]
    assert controller.status()["startup_failure_code"] == "release_contract_invalid"
    assert controller.status()["startup_failure_stage"] == "runtime_discovery"
    for action in (
        controller.start,
        controller.stop,
        controller.restart,
        controller.auto_restart,
        controller.open_console,
        controller.open_pairing,
        controller.open_devices,
        controller.open_upload_links,
        controller.open_backups,
        controller.open_diagnostics,
        controller.open_settings,
        controller.export_diagnostics,
    ):
        with pytest.raises(ManagerShuttingDownError):
            action()


def test_missing_installed_service_disables_scm_actions(tmp_path: Path) -> None:
    config = _installed_config(tmp_path, port=8101, service_suffix="Missing")

    class MissingRuntime(FakeRuntime):
        def status(self) -> RuntimeStatus:
            snapshot = super().status()
            return RuntimeStatus(
                **{
                    **snapshot.__dict__,
                    "mode": "installed",
                    "running": False,
                    "healthy": False,
                    "backend_service_state": "missing",
                    "database_service_state": "running",
                    "health_state": "pending",
                    "health_detail": "backend service missing",
                },
            )

    status = AppController(MissingRuntime(), config).status()

    assert status["backend_service_state"] == "missing"
    assert status["service_controls_available"] is False
    assert "maintenance_available" not in status


# ── Desktop product principal (218-E two-phase credential commit) ─────────

from backend_manager.product_data import (  # noqa: E402
    PendingProductSession,
    ProductDataError,
    derive_desktop_pending_token,
    new_activation_attempt,
)
from backend_manager.product_identity import ProductCredentialError, ProductSession  # noqa: E402
from backend_manager.product_recovery import RebindRecovery  # noqa: E402

_INSTALLATION_ID = "ticketbox-0123456789abcdef0123456789abcdef"
_STAGED_EXPIRY = "2026-07-26T22:20:00Z"
_REAL_EXPIRY = "2026-10-16T00:00:00Z"


def _product_session(
    token: str = "tbx-desktop-secret",
    *,
    ledger_id: str = "owner",
    role: str = "owner",
    expires_at: str | None = _REAL_EXPIRY,
) -> ProductSession:
    return ProductSession(
        session_token=token,
        account_name="我",
        ledger_id=ledger_id,
        ledger_name="我的小票夹" if ledger_id == "owner" else "家庭账本",
        device_name="小票夹 Desktop",
        role=role,
        expires_at=expires_at,
    )


def _pending_for(
    *,
    ledger_id: str = "owner",
    role: str = "owner",
    token: str | None = None,
) -> PendingProductSession:
    attempt_id, attempt_secret = new_activation_attempt()
    derived = token or derive_desktop_pending_token(attempt_secret, attempt_id)
    return PendingProductSession(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        session=ProductSession(
            session_token=derived,
            account_name="我",
            ledger_id=ledger_id,
            ledger_name="我的小票夹" if ledger_id == "owner" else "家庭账本",
            device_name="小票夹 Desktop",
            role=role,
            expires_at=_STAGED_EXPIRY,
        ),
    )


def _activate_pending(
    _origin: str,
    pending: PendingProductSession,
    _previous: str | None,
    **_kwargs,
) -> ProductSession:
    """Mirror product_data.activate: same derived value, fresh real expiry."""
    return ProductSession(
        session_token=pending.session.session_token,
        account_name=pending.session.account_name,
        ledger_id=pending.session.ledger_id,
        ledger_name=pending.session.ledger_name,
        device_name=pending.session.device_name,
        role=pending.session.role,
        expires_at=_REAL_EXPIRY,
    )


def _stores(primary: ProductSession | None = None):
    """In-memory stand-ins for the two WinCred slots."""
    sessions: dict[str, ProductSession] = {}
    if primary is not None:
        sessions[_INSTALLATION_ID] = primary
    recoveries: dict[str, RebindRecovery] = {}
    return (
        sessions,
        recoveries,
        {
            "product_session_loader": sessions.get,
            "product_session_saver": sessions.__setitem__,
            "product_session_deleter": lambda credential_id: sessions.pop(credential_id, None),
            "product_recovery_loader": recoveries.get,
            "product_recovery_saver": recoveries.__setitem__,
            "product_recovery_deleter": lambda credential_id: recoveries.pop(credential_id, None),
        },
    )


def test_pair_stages_activates_and_promotes_with_previous_proof_in_order() -> None:
    current = _product_session()
    pending = _pending_for(ledger_id="owner")
    sessions, recoveries, store = _stores(current)
    events: list[tuple[str, str]] = []

    def pair(*_args, **_kwargs) -> PendingProductSession:
        events.append(("pair", ""))
        return pending

    def activate(_origin, value, previous, **_kwargs) -> ProductSession:
        events.append(("activate", str(previous)))
        return _activate_pending(_origin, value, previous, **_kwargs)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=pair,
        product_session_activator=activate,
        **store,
    )

    projection = controller.pair_product_principal("12345678")

    assert projection["configured"] is True
    assert projection["ledger_id"] == "owner"
    assert "session_token" not in projection
    # Same-ledger re-pair: the predecessor proof goes to activate, and #219
    # retires it server-side — no client revoke.
    assert events == [("pair", ""), ("activate", current.session_token)]
    assert sessions[_INSTALLATION_ID].session_token == pending.session.session_token
    assert sessions[_INSTALLATION_ID].expires_at == _REAL_EXPIRY
    assert recoveries == {}


def test_pair_cross_ledger_skips_previous_and_revokes_old_after_promotion() -> None:
    current = _product_session(ledger_id="owner")
    pending = _pending_for(ledger_id="family", role="member")
    sessions, recoveries, store = _stores(current)
    events: list[tuple[str, str]] = []

    def activate(_origin, value, previous, **_kwargs) -> ProductSession:
        events.append(("activate", str(previous)))
        return _activate_pending(_origin, value, previous, **_kwargs)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_session_activator=activate,
        product_session_revoker=lambda _origin, token, **_kwargs: events.append(("revoke", token)),
        **store,
    )

    projection = controller.pair_product_principal("12345678")

    assert projection["ledger_id"] == "family"
    # A cross-ledger credential is not a valid activation predecessor: no
    # previous header, and the old credential is retired only AFTER the new
    # one is durable.
    assert events == [("activate", "None"), ("revoke", current.session_token)]
    assert sessions[_INSTALLATION_ID].session_token == pending.session.session_token


def test_rebind_recovery_store_failure_never_activates_pending_b() -> None:
    current = _product_session()
    pending = _pending_for(ledger_id="family")
    sessions, _recoveries, store = _stores(current)
    activations: list[str] = []

    def fail_recovery_save(_credential_id: str, _recovery: RebindRecovery) -> None:
        raise ProductCredentialError("synthetic recovery store failure")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_session_activator=lambda _origin, value, _previous, **_kwargs: (
            activations.append(value.session_token),
            _activate_pending(_origin, value, _previous, **_kwargs),
        )[-1],
        **{**store, "product_recovery_saver": fail_recovery_save},
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.error == "product_credential_unavailable"
    assert activations == []
    assert sessions[_INSTALLATION_ID] == current


@pytest.mark.parametrize("operation", ["pair", "switch"])
def test_rebind_same_token_fails_before_recovery_or_activation(operation: str) -> None:
    current = _product_session()
    sessions, recoveries, store = _stores(current)
    activations: list[str] = []
    pending = _pending_for(ledger_id="owner", token=current.session_token)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_ledger_switcher=lambda *_args, **_kwargs: pending,
        product_session_activator=lambda _origin, value, _previous, **_kwargs: (
            activations.append(value.session_token),
            _activate_pending(_origin, value, _previous, **_kwargs),
        )[-1],
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        if operation == "pair":
            controller.pair_product_principal("12345678")
        else:
            controller.switch_product_principal_ledger("family")

    assert error.value.status_code == 502
    assert error.value.error == "product_identity_rotation_required"
    assert activations == []
    assert recoveries == {}
    assert sessions[_INSTALLATION_ID] == current


def test_activation_response_loss_replays_recovery_with_fresh_metadata() -> None:
    current = _product_session()
    pending = _pending_for(ledger_id="owner")
    sessions, recoveries, store = _stores(current)
    calls: list[str | None] = []

    def activate(_origin, value, previous, **_kwargs) -> ProductSession:
        calls.append(previous)
        if len(calls) == 1:
            raise ProductDataError("synthetic committed response loss", status_code=503)
        return _activate_pending(_origin, value, previous, **_kwargs)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_session_activator=activate,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")
    assert error.value.error == "product_rebind_recovery_pending"
    assert error.value.status_code == 503
    assert _INSTALLATION_ID in recoveries
    assert sessions[_INSTALLATION_ID] == current

    projection = controller.product_principal()

    # The idempotent activate replay committed the same value; the projection
    # carries the replay response's fresh expiry, not the stale staged TTL.
    assert projection["configured"] is True
    assert projection["expires_at"] == _REAL_EXPIRY
    assert projection["expires_at"] != _STAGED_EXPIRY
    assert sessions[_INSTALLATION_ID].session_token == pending.session.session_token
    assert recoveries == {}
    assert calls == [current.session_token, current.session_token]


def test_primary_store_failure_leaves_recovery_replayable() -> None:
    current = _product_session()
    pending = _pending_for(ledger_id="family")
    sessions, recoveries, store = _stores(current)
    primary_writes = {"count": 0}

    def flaky_primary_save(credential_id: str, session: ProductSession) -> None:
        primary_writes["count"] += 1
        if primary_writes["count"] == 1:
            raise ProductCredentialError("synthetic primary save failure")
        sessions[credential_id] = session

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_session_activator=_activate_pending,
        product_session_revoker=lambda *_args, **_kwargs: None,
        **{**store, "product_session_saver": flaky_primary_save},
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert sessions[_INSTALLATION_ID] == current
    assert _INSTALLATION_ID in recoveries

    projection = controller.product_principal()
    assert projection["ledger_id"] == "family"
    assert sessions[_INSTALLATION_ID].session_token == pending.session.session_token
    assert recoveries == {}


def test_activation_failure_keeps_recovery_and_primary_unchanged() -> None:
    current = _product_session()
    pending = _pending_for(ledger_id="family")
    sessions, recoveries, store = _stores(current)

    def activation_failure(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("synthetic activation response loss", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *_args, **_kwargs: pending,
        product_session_activator=activation_failure,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.status_code == 503
    assert error.value.error == "product_rebind_recovery_pending"
    assert sessions[_INSTALLATION_ID] == current
    assert _INSTALLATION_ID in recoveries
    assert pending.activation_attempt_secret not in str(error.value)
    assert pending.session.session_token not in str(error.value)


def test_expired_recovery_is_cleaned_and_current_survives() -> None:
    current = _product_session()
    sessions, recoveries, store = _stores(current)
    attempt_id, attempt_secret = new_activation_attempt()
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        activation_expires_at=_STAGED_EXPIRY,
    )

    def reject_expired(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("synthetic expired activation", error="invalid_token", status_code=401)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_activator=reject_expired,
        **store,
    )

    projection = controller.product_principal()

    assert projection["ledger_id"] == current.ledger_id
    assert sessions[_INSTALLATION_ID] == current
    assert recoveries == {}


def test_switch_two_phase_omits_previous_and_revokes_source_after_promotion() -> None:
    current = _product_session(ledger_id="owner")
    pending = _pending_for(ledger_id="family", role="viewer")
    sessions, recoveries, store = _stores(current)
    events: list[tuple[str, str]] = []
    switch_calls: list[tuple[str, str, str]] = []

    def switcher(origin: str, ledger_id: str, token: str, **_kwargs) -> PendingProductSession:
        switch_calls.append((origin, ledger_id, token))
        return pending

    def activate(_origin, value, previous, **_kwargs) -> ProductSession:
        events.append(("activate", str(previous)))
        return _activate_pending(_origin, value, previous, **_kwargs)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=switcher,
        product_session_activator=activate,
        product_session_revoker=lambda _origin, token, **_kwargs: events.append(("revoke", token)),
        **store,
    )

    projection = controller.switch_product_principal_ledger("family")

    assert projection["ledger_id"] == "family"
    assert projection["role"] == "viewer"
    assert "session_token" not in projection
    assert switch_calls == [("http://127.0.0.1:8000", "family", current.session_token)]
    # 218-E switch law: never send the source credential as the activation
    # predecessor; revoke it explicitly only after the new one is durable.
    assert events == [("activate", "None"), ("revoke", current.session_token)]
    assert sessions[_INSTALLATION_ID].session_token == pending.session.session_token
    assert recoveries == {}


def test_switch_same_ledger_short_circuits_without_backend_calls() -> None:
    current = _product_session(ledger_id="owner")
    sessions, recoveries, store = _stores(current)
    calls: list[str] = []

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=lambda *_args, **_kwargs: calls.append("switch"),
        product_session_activator=lambda *_args, **_kwargs: calls.append("activate"),
        **store,
    )

    projection = controller.switch_product_principal_ledger("owner")

    assert projection["ledger_id"] == "owner"
    assert calls == []
    assert recoveries == {}


def test_switch_prepare_401_clears_the_installation_credential() -> None:
    current = _product_session()
    sessions, _recoveries, store = _stores(current)

    def denied(*_args, **_kwargs):
        raise ProductDataError("桌面身份已失效", error="invalid_token", status_code=401)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=denied,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.switch_product_principal_ledger("family")

    assert error.value.status_code == 401
    assert sessions == {}


def test_switch_revoke_failure_leaves_durable_replacement() -> None:
    current = _product_session(ledger_id="owner")
    pending = _pending_for(ledger_id="family")
    sessions, _recoveries, store = _stores(current)

    def flaky_revoker(*_args, **_kwargs) -> None:
        raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=lambda *_args, **_kwargs: pending,
        product_session_activator=_activate_pending,
        product_session_revoker=flaky_revoker,
        **store,
    )

    projection = controller.switch_product_principal_ledger("family")

    assert projection["ledger_id"] == "family"
    assert sessions[_INSTALLATION_ID].session_token == pending.session.session_token


def test_unpair_revokes_deletes_and_tolerates_401() -> None:
    current = _product_session()
    sessions, _recoveries, store = _stores(current)
    revoked: list[str] = []

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    assert controller.unpair_product_principal() == {"configured": False}
    assert revoked == [current.session_token]
    assert sessions == {}

    dead = _product_session()
    sessions2, _recoveries2, store2 = _stores(dead)

    def already_dead(*_args, **_kwargs) -> None:
        raise ProductDataError("gone", error="invalid_token", status_code=401)

    controller2 = AppController(
        FakeRuntime(),
        _config(),
        product_session_revoker=already_dead,
        **store2,
    )
    assert controller2.unpair_product_principal() == {"configured": False}
    assert sessions2 == {}


def test_bridge_context_returns_secrets_only_in_process_and_fails_closed() -> None:
    current = _product_session()
    _sessions, _recoveries, store = _stores(current)

    controller = AppController(FakeRuntime(), _config(), **store)
    context = controller.product_bridge_context()

    assert context.backend_origin == "http://127.0.0.1:8000"
    assert context.app_token == current.session_token

    empty = AppController(FakeRuntime(), _config(), **_stores()[2])
    with pytest.raises(ProductDataError) as error:
        empty.product_bridge_context()
    assert error.value.status_code == 401
    assert error.value.error == "product_principal_required"


def test_product_actions_are_serialized_on_the_session_lock() -> None:
    activate_started = threading.Event()
    release_activate = threading.Event()
    switch_called = threading.Event()
    errors: list[BaseException] = []
    current = _product_session()
    pending = _pending_for(ledger_id="family")
    _sessions, _recoveries, store = _stores(current)

    def slow_activate(_origin, value, previous, **_kwargs) -> ProductSession:
        activate_started.set()
        assert release_activate.wait(timeout=2)
        return _activate_pending(_origin, value, previous, **_kwargs)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *_args, **_kwargs: _pending_for(),
        product_ledger_switcher=lambda *_args, **_kwargs: (switch_called.set(), pending)[-1],
        product_session_activator=slow_activate,
        **store,
    )

    def run_pair() -> None:
        try:
            controller.pair_product_principal("12345678")
        except Exception as exc:  # pragma: no cover - asserted after join
            errors.append(exc)

    def run_switch() -> None:
        try:
            controller.switch_product_principal_ledger("family")
        except Exception as exc:  # pragma: no cover - asserted after join
            errors.append(exc)

    pair_thread = threading.Thread(target=run_pair)
    switch_thread = threading.Thread(target=run_switch)
    pair_thread.start()
    assert activate_started.wait(timeout=2)
    switch_thread.start()
    assert switch_called.wait(timeout=0.1) is False
    release_activate.set()
    pair_thread.join(timeout=2)
    switch_thread.join(timeout=2)

    assert errors == []
    assert switch_called.is_set()


# ── 218-E review fixes: cross-ledger revoke cleanup + bridged 401 clearing ──


def test_recovery_promotion_revokes_cross_ledger_predecessor() -> None:
    """Reconcile path (manager died mid-switch): once the recovered B is
    durable, the source-ledger credential is revoked, not left to TTL."""
    current = _product_session(ledger_id="owner")
    sessions, recoveries, store = _stores(current)
    attempt_id, attempt_secret = new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token=current.session_token,
    )
    revoked: list[str] = []

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_activator=_activate_pending,
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    projection = controller.product_principal()

    assert projection["ledger_id"] == "family"
    assert revoked == [current.session_token]
    assert sessions[_INSTALLATION_ID].session_token == derived
    assert recoveries == {}


def test_superseded_revoke_failure_keeps_retryable_cleanup_record() -> None:
    current = _product_session(ledger_id="owner")
    sessions, recoveries, store = _stores(current)
    pending = _pending_for(ledger_id="family", role="viewer")
    attempts = {"count": 0}

    def flaky_revoker(_origin, _token, **_kwargs) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=lambda *_args, **_kwargs: pending,
        product_session_activator=_activate_pending,
        product_session_revoker=flaky_revoker,
        **store,
    )

    # The switch itself succeeds (replacement is durable), but the owed
    # revoke is NOT silently dropped: the recovery record stays as a
    # retryable cleanup marker holding exactly the superseded token.
    projection = controller.switch_product_principal_ledger("family")
    assert projection["ledger_id"] == "family"
    assert sessions[_INSTALLATION_ID].session_token == pending.session.session_token
    assert _INSTALLATION_ID in recoveries
    assert recoveries[_INSTALLATION_ID].superseded_session_token == current.session_token

    # The next principal read retries the owed revoke; only a durable
    # cleanup drops the record.
    assert controller.product_principal()["ledger_id"] == "family"
    assert attempts["count"] == 2
    assert recoveries == {}


def test_note_product_bridge_auth_failure_clears_dead_credential() -> None:
    current = _product_session()
    sessions, _recoveries, store = _stores(current)
    controller = AppController(FakeRuntime(), _config(), **store)

    assert controller.note_product_bridge_auth_failure(403, current.session_token) is False
    assert sessions[_INSTALLATION_ID] == current

    assert controller.note_product_bridge_auth_failure(401, current.session_token) is True
    assert sessions == {}
    assert controller.product_principal() == {"configured": False}


def test_bridge_auth_failure_never_wipes_a_fresher_session() -> None:
    """Race: the relayed request carried the already-superseded token A while
    the store now holds the valid B — the 401 must retire A only, never B."""
    replacement = _product_session(token="tbx-fresh-B", ledger_id="family")
    sessions, _recoveries, store = _stores(replacement)
    controller = AppController(FakeRuntime(), _config(), **store)

    deleted = controller.note_product_bridge_auth_failure(401, "tbx-superseded-A")

    assert deleted is False
    assert sessions[_INSTALLATION_ID].session_token == "tbx-fresh-B"
    assert controller.product_principal()["ledger_id"] == "family"


# ── P2 regression: the owed superseded revoke survives teardown paths ───────


def test_reconcile_401_still_attempts_owed_superseded_revoke() -> None:
    """B died server-side while the A-revoke was still owed: the reconcile
    401 branch must attempt it before dropping the recovery record."""
    sessions, recoveries, store = _stores(None)
    attempt_id, attempt_secret = new_activation_attempt()
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-superseded-A",
    )
    revoked: list[str] = []

    def dead_attempt(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("staged attempt dead", error="invalid_token", status_code=401)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_activator=dead_attempt,
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    assert controller.product_principal() == {"configured": False}

    assert revoked == ["tbx-superseded-A"]
    assert recoveries == {}


def test_unpair_revokes_owed_superseded_before_dropping_recovery() -> None:
    attempt_id, attempt_secret = new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    current = _product_session(token=derived, ledger_id="family")
    sessions, recoveries, store = _stores(current)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-A",
    )
    revoked: list[str] = []

    def flaky_revoker(_origin, token, **_kwargs) -> None:
        revoked.append(token)
        if len(revoked) == 1:
            # The reconcile-time retry fails transiently; the unpair-time
            # backstop must still collect the owed revoke afterwards.
            raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_revoker=flaky_revoker,
        **store,
    )

    assert controller.unpair_product_principal() == {"configured": False}

    # Reconcile's superseded retry (failed), the unpair-time retry that must
    # succeed BEFORE teardown starts, then the primary revoke.
    assert revoked == ["tbx-old-A", "tbx-old-A", derived]
    assert sessions == {}
    assert recoveries == {}


def test_unpair_with_dead_primary_still_collects_superseded() -> None:
    sessions, recoveries, store = _stores(None)
    attempt_id, attempt_secret = new_activation_attempt()
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-superseded-A",
    )
    revoked: list[str] = []

    def dead_attempt(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("staged attempt dead", error="invalid_token", status_code=401)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_activator=dead_attempt,
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    assert controller.unpair_product_principal() == {"configured": False}
    assert revoked == ["tbx-superseded-A"]
    assert recoveries == {}


# ── P0/P2 regression: 401 self-heal must never kill a live primary ──────────


def test_reconcile_401_never_revokes_a_still_live_primary() -> None:
    """Cross-ledger re-pair staged (superseded=A pre-written), activation
    transiently failed, staged attempt then expired server-side: A is still
    the live primary and must NOT be revoked by a status read."""
    current = _product_session(ledger_id="owner")
    sessions, recoveries, store = _stores(current)
    attempt_id, attempt_secret = new_activation_attempt()
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token=current.session_token,
    )
    revoked: list[str] = []

    def dead_attempt(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("staged attempt expired", error="invalid_token", status_code=401)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_activator=dead_attempt,
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    projection = controller.product_principal()

    # A was never displaced: it stays the live identity, no revoke is issued,
    # and only the stale ceremony record is cleaned.
    assert revoked == []
    assert projection["configured"] is True
    assert projection["ledger_id"] == "owner"
    assert sessions[_INSTALLATION_ID].session_token == current.session_token
    assert recoveries == {}


def test_reconcile_401_keeps_record_when_superseded_revoke_fails_transiently() -> None:
    sessions, recoveries, store = _stores(None)
    attempt_id, attempt_secret = new_activation_attempt()
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-A",
    )
    revoked: list[str] = []

    def dead_attempt(*_args, **_kwargs) -> ProductSession:
        raise ProductDataError("staged attempt expired", error="invalid_token", status_code=401)

    def flaky_revoker(_origin, token, **_kwargs) -> None:
        revoked.append(token)
        if len(revoked) == 1:
            raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_activator=dead_attempt,
        product_session_revoker=flaky_revoker,
        **store,
    )

    assert controller.product_principal() == {"configured": False}
    # A non-death failure keeps the cleanup record retryable instead of
    # orphaning the owed revoke until TTL.
    assert revoked == ["tbx-old-A"]
    assert _INSTALLATION_ID in recoveries

    assert controller.product_principal() == {"configured": False}
    assert revoked == ["tbx-old-A", "tbx-old-A"]
    assert recoveries == {}


# ── Round-3 regressions: unpair gate, identity gate, shutdown seal, provisional attempt ──


def test_unpair_refuses_to_complete_while_superseded_cleanup_fails() -> None:
    attempt_id, attempt_secret = new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    current = _product_session(token=derived, ledger_id="family")
    sessions, recoveries, store = _stores(current)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-A",
    )
    attempts = {"count": 0}

    def failing_revoker(_origin, token, **_kwargs) -> None:
        attempts["count"] += 1
        raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_revoker=failing_revoker,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.unpair_product_principal()

    assert error.value.status_code == 503
    assert error.value.error == "product_cleanup_pending"
    # Teardown never started: the primary and the cleanup record both survive.
    assert sessions[_INSTALLATION_ID].session_token == derived
    assert _INSTALLATION_ID in recoveries

    # The next attempt completes once the backend is reachable again.
    controller2 = AppController(
        FakeRuntime(),
        _config(),
        product_session_revoker=lambda _origin, token, **_kwargs: None,
        **store,
    )
    assert controller2.unpair_product_principal() == {"configured": False}
    assert sessions == {}
    assert recoveries == {}


class _DegradedRuntime:
    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode="source",
            running=True,
            healthy=False,
            pid=None,
            uptime_seconds=1,
            auto_restart=True,
            auto_restart_configurable=True,
            restarts=0,
            backend_service_state=None,
            database_service_state=None,
            log=["degraded"],
            health_state="mismatch",
            health_detail="installation identity mismatch",
            runtime_access_state="available",
            owner_state="configured",
        )


def test_reconcile_never_replays_proof_against_unverified_runtime() -> None:
    sessions, recoveries, store = _stores(None)
    attempt_id, attempt_secret = new_activation_attempt()
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
    )
    activations: list[str] = []

    controller = AppController(
        _DegradedRuntime(),
        _config(),
        product_session_activator=lambda _origin, value, _previous, **_kwargs: (
            activations.append(value.session_token),
            _activate_pending(_origin, value, _previous, **_kwargs),
        )[-1],
        **store,
    )

    assert controller.product_principal() == {"configured": False}

    # The proof is never sent to an identity-unverified backend; the record
    # (the only replay material) survives for the next verified runtime.
    assert activations == []
    assert _INSTALLATION_ID in recoveries


def test_product_mutations_honor_the_shutdown_seal() -> None:
    controller = AppController(FakeRuntime(), _config(), **_stores()[2])
    controller.request_manager_shutdown()

    with pytest.raises(ManagerShuttingDownError):
        controller.pair_product_principal("12345678")
    with pytest.raises(ManagerShuttingDownError):
        controller.unpair_product_principal()
    with pytest.raises(ManagerShuttingDownError):
        controller.switch_product_principal_ledger("family")


def test_pair_reuses_the_provisional_attempt_after_response_loss() -> None:
    sessions, recoveries, store = _stores(None)
    seen_attempts: list[tuple[str, str]] = []
    calls = {"count": 0}

    def pairer(_origin, _code, *, attempt, **_kwargs) -> PendingProductSession:
        calls["count"] += 1
        seen_attempts.append(attempt)
        if calls["count"] == 1:
            # Backend committed, but the response died on the wire.
            raise ProductDataError("synthetic response loss", status_code=503)
        attempt_id, attempt_secret = attempt
        return PendingProductSession(
            activation_attempt_id=attempt_id,
            activation_attempt_secret=attempt_secret,
            session=ProductSession(
                session_token=derive_desktop_pending_token(attempt_secret, attempt_id),
                account_name="我",
                ledger_id="owner",
                ledger_name="我的小票夹",
                device_name="小票夹 Desktop",
                role="owner",
                expires_at=_STAGED_EXPIRY,
            ),
        )

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=pairer,
        product_session_activator=_activate_pending,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")
    assert error.value.status_code == 503
    # The provisional record persisted the proof before the code was consumed.
    assert _INSTALLATION_ID in recoveries
    assert recoveries[_INSTALLATION_ID].ledger_id == ""

    projection = controller.pair_product_principal("12345678")

    assert projection["configured"] is True
    assert seen_attempts[0] == seen_attempts[1], "retry must reuse the exact attempt proof"
    assert recoveries == {}


def test_invalid_pairing_code_drops_the_provisional_attempt() -> None:
    sessions, recoveries, store = _stores(None)
    seen_attempts: list[tuple[str, str]] = []
    calls = {"count": 0}

    def pairer(_origin, _code, *, attempt, **_kwargs) -> PendingProductSession:
        calls["count"] += 1
        seen_attempts.append(attempt)
        if calls["count"] == 1:
            raise ProductDataError("bad code", error="invalid_pairing_code", status_code=401)
        return _pending_for(ledger_id="owner")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=pairer,
        product_session_activator=_activate_pending,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("00000000")
    assert error.value.error == "invalid_pairing_code"
    assert recoveries == {}

    projection = controller.pair_product_principal("87654321")
    assert projection["configured"] is True
    assert seen_attempts[0] != seen_attempts[1], "a rejected code must not pin the next attempt"


# ── Round-4 regressions: owed cleanup survives pairing; terminal attempt drops provisional ──


def test_pair_refuses_to_start_while_superseded_cleanup_is_outstanding() -> None:
    attempt_id, attempt_secret = new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    current = _product_session(token=derived, ledger_id="family")
    sessions, recoveries, store = _stores(current)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-X",
    )
    pair_calls: list = []

    def failing_revoker(_origin, token, **_kwargs) -> None:
        raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda *args, **kwargs: pair_calls.append((args, kwargs)),
        product_session_revoker=failing_revoker,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")

    assert error.value.status_code == 503
    assert error.value.error == "product_cleanup_pending"
    # No provisional overwrite happened: the owed record is fully intact.
    assert pair_calls == []
    assert recoveries[_INSTALLATION_ID].superseded_session_token == "tbx-old-X"
    assert sessions[_INSTALLATION_ID].session_token == derived


def test_pair_settles_owed_cleanup_then_proceeds() -> None:
    attempt_id, attempt_secret = new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    current = _product_session(token=derived, ledger_id="family")
    sessions, recoveries, store = _stores(current)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-X",
    )
    revoked: list[str] = []

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda _origin, _code, *, attempt, **_kwargs: PendingProductSession(
            activation_attempt_id=attempt[0],
            activation_attempt_secret=attempt[1],
            session=ProductSession(
                session_token=derive_desktop_pending_token(attempt[1], attempt[0]),
                account_name="我",
                ledger_id="family",
                ledger_name="家庭账本",
                device_name="小票夹 Desktop",
                role="member",
                expires_at=_STAGED_EXPIRY,
            ),
        ),
        product_session_activator=_activate_pending,
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    projection = controller.pair_product_principal("12345678")

    assert projection["configured"] is True
    assert revoked[0] == "tbx-old-X"
    assert recoveries == {}


def test_terminal_attempt_answers_drop_the_provisional_record() -> None:
    sessions, recoveries, store = _stores(None)
    seen_attempts: list[tuple[str, str]] = []
    calls = {"count": 0}

    def closed_pairer(_origin, _code, *, attempt, **_kwargs) -> PendingProductSession:
        calls["count"] += 1
        seen_attempts.append(attempt)
        if calls["count"] == 1:
            raise ProductDataError("closed", error="pairing_attempt_closed", status_code=409)
        return PendingProductSession(
            activation_attempt_id=attempt[0],
            activation_attempt_secret=attempt[1],
            session=ProductSession(
                session_token=derive_desktop_pending_token(attempt[1], attempt[0]),
                account_name="我",
                ledger_id="owner",
                ledger_name="我的小票夹",
                device_name="小票夹 Desktop",
                role="owner",
                expires_at=_STAGED_EXPIRY,
            ),
        )

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=closed_pairer,
        product_session_activator=_activate_pending,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("12345678")
    assert error.value.error == "pairing_attempt_closed"
    assert recoveries == {}

    projection = controller.pair_product_principal("12345678")
    assert projection["configured"] is True
    assert seen_attempts[0] != seen_attempts[1], "a closed ceremony must not be retried forever"


def test_reused_provisional_with_mismatched_code_keeps_the_record() -> None:
    sessions, recoveries, store = _stores(None)
    calls = {"count": 0}

    def wrong_code_pairer(_origin, _code, *, attempt, **_kwargs) -> PendingProductSession:
        calls["count"] += 1
        if calls["count"] == 1:
            # First call commits (response lost); the second, different code,
            # is a proof/code mismatch on that committed ceremony.
            raise ProductDataError("response loss", status_code=503)
        raise ProductDataError("mismatch", error="invalid_pairing_code", status_code=401)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=wrong_code_pairer,
        product_session_activator=_activate_pending,
        **store,
    )

    with pytest.raises(ProductDataError):
        controller.pair_product_principal("12345678")
    assert recoveries[_INSTALLATION_ID].ledger_id == ""

    with pytest.raises(ProductDataError) as error:
        controller.pair_product_principal("99999999")
    assert error.value.error == "invalid_pairing_code"
    # A possibly-committed ceremony is never cleared by a mismatched retry.
    assert _INSTALLATION_ID in recoveries


# ── Round-5 regressions: provisional TTL escape, gate P0-guard, gate-revoke branch ──


def test_provisional_attempt_expires_so_a_regenerated_code_can_pair() -> None:
    sessions, recoveries, store = _stores(None)
    seen_attempts: list[tuple[str, str]] = []
    calls = {"count": 0}

    def lossy_pairer(_origin, _code, *, attempt, **_kwargs) -> PendingProductSession:
        calls["count"] += 1
        seen_attempts.append(attempt)
        if calls["count"] == 1:
            raise ProductDataError("synthetic response loss", status_code=503)
        return PendingProductSession(
            activation_attempt_id=attempt[0],
            activation_attempt_secret=attempt[1],
            session=ProductSession(
                session_token=derive_desktop_pending_token(attempt[1], attempt[0]),
                account_name="我",
                ledger_id="owner",
                ledger_name="我的小票夹",
                device_name="小票夹 Desktop",
                role="owner",
                expires_at=_STAGED_EXPIRY,
            ),
        )

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lossy_pairer,
        product_session_activator=_activate_pending,
        **store,
    )

    with pytest.raises(ProductDataError):
        controller.pair_product_principal("12345678")
    assert _INSTALLATION_ID in recoveries

    # The user lost the original code and the provisional proof aged past the
    # backend pending TTL: it is definitively closed, so it must not wedge
    # this installation behind proof/code mismatches.
    stale = recoveries[_INSTALLATION_ID]
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=stale.activation_attempt_id,
        activation_attempt_secret=stale.activation_attempt_secret,
        activation_expires_at="2020-01-01T00:00:00+00:00",
    )
    assert controller.product_principal() == {"configured": False}
    assert recoveries == {}

    projection = controller.pair_product_principal("87654321")
    assert projection["configured"] is True
    assert seen_attempts[0] != seen_attempts[1], "expired provisional must yield a fresh attempt"
    assert recoveries == {}


def test_pair_gate_revokes_owed_superseded_when_reconcile_retry_failed() -> None:
    """P2-1 branch: reconcile's owed retry fails transiently, then the pair
    gate's own revoke succeeds and lets the pair proceed."""
    attempt_id, attempt_secret = new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    current = _product_session(token=derived, ledger_id="family")
    sessions, recoveries, store = _stores(current)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-A",
    )
    revoked: list[str] = []

    def flaky_revoker(_origin, token, **_kwargs) -> None:
        revoked.append(token)
        if len(revoked) == 1:
            raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_pairer=lambda _origin, _code, *, attempt, **_kwargs: PendingProductSession(
            activation_attempt_id=attempt[0],
            activation_attempt_secret=attempt[1],
            session=ProductSession(
                session_token=derive_desktop_pending_token(attempt[1], attempt[0]),
                account_name="我",
                ledger_id="family",
                ledger_name="家庭账本",
                device_name="小票夹 Desktop",
                role="member",
                expires_at=_STAGED_EXPIRY,
            ),
        ),
        product_session_activator=_activate_pending,
        product_session_revoker=flaky_revoker,
        **store,
    )

    projection = controller.pair_product_principal("12345678")

    assert projection["configured"] is True
    assert revoked == ["tbx-old-A", "tbx-old-A"]
    assert recoveries == {}


class _FlippingRuntime:
    def __init__(self, healthy: RuntimeStatus, degraded: RuntimeStatus) -> None:
        self._healthy = healthy
        self._degraded = degraded
        self.calls = 0

    def status(self) -> RuntimeStatus:
        self.calls += 1
        return self._healthy if self.calls == 1 else self._degraded


def test_pair_gate_never_revokes_superseded_that_is_still_the_live_primary() -> None:
    """P2-2 race: config check passes healthy, reconcile's availability check
    flips negative and early-returns, leaving an uncommitted ceremony whose
    superseded IS the live primary at the pair gate."""
    healthy = FakeRuntime().status()
    degraded = _DegradedRuntime().status()
    current = _product_session(ledger_id="owner")
    sessions, recoveries, store = _stores(current)
    attempt_id, attempt_secret = new_activation_attempt()
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="member",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token=current.session_token,
    )
    revoked: list[str] = []

    controller = AppController(
        _FlippingRuntime(healthy, degraded),
        _config(),
        product_session_pairer=lambda _origin, _code, *, attempt, **_kwargs: PendingProductSession(
            activation_attempt_id=attempt[0],
            activation_attempt_secret=attempt[1],
            session=ProductSession(
                session_token=derive_desktop_pending_token(attempt[1], attempt[0]),
                account_name="我",
                ledger_id="owner",
                ledger_name="我的小票夹",
                device_name="小票夹 Desktop",
                role="owner",
                expires_at=_STAGED_EXPIRY,
            ),
        ),
        product_session_activator=_activate_pending,
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    projection = controller.pair_product_principal("12345678")

    # The live primary was never at risk: no direct revoke, only the stale
    # attempt record dropped; the re-pair completed through the normal flow.
    assert projection["configured"] is True
    assert current.session_token not in revoked
    assert recoveries == {}


# ── Round-6: pending-TTL contract pin (backend is the TTL authority) ────────


def test_provisional_attempt_ttl_mirrors_the_backend_pending_ttl() -> None:
    """Contract pin: the backend authority is
    ``backend/app/services/desktop_activation_service.py::
    DESKTOP_PENDING_TOKEN_TTL_SECONDS`` (300s). The desktop deadline mirrors it
    and only the skew margin extends past it, so a provisional proof is never
    retired while it could still be live server-side."""
    from backend_manager.app_controller import (
        _PROVISIONAL_ATTEMPT_EXPIRY_MARGIN_SECONDS,
        _PROVISIONAL_ATTEMPT_TTL_SECONDS,
    )

    assert _PROVISIONAL_ATTEMPT_TTL_SECONDS == 300
    assert _PROVISIONAL_ATTEMPT_EXPIRY_MARGIN_SECONDS > 0


# ── Round-4 regressions: switch gate + live role rendering ──────────────────


def test_switch_refuses_to_overwrite_a_recovery_with_owed_cleanup() -> None:
    """A→B switch whose A-revoke failed transiently leaves the owed record;
    a second switch (B→C) must settle or refuse — never overwrite the slot."""
    attempt_id, attempt_secret = new_activation_attempt()
    derived_b = derive_desktop_pending_token(attempt_secret, attempt_id)
    current_b = _product_session(token=derived_b, ledger_id="family", role="viewer")
    sessions, recoveries, store = _stores(current_b)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-A",
    )
    switch_calls: list = []

    def failing_revoker(_origin, token, **_kwargs) -> None:
        raise ProductDataError("backend unreachable", status_code=503)

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=lambda *args, **kwargs: switch_calls.append((args, kwargs)),
        product_session_revoker=failing_revoker,
        **store,
    )

    with pytest.raises(ProductDataError) as error:
        controller.switch_product_principal_ledger("third")

    assert error.value.status_code == 503
    assert error.value.error == "product_cleanup_pending"
    assert switch_calls == []
    assert recoveries[_INSTALLATION_ID].superseded_session_token == "tbx-old-A"
    assert sessions[_INSTALLATION_ID].session_token == derived_b


def test_switch_settles_owed_cleanup_then_proceeds_to_next_ledger() -> None:
    attempt_id, attempt_secret = new_activation_attempt()
    derived_b = derive_desktop_pending_token(attempt_secret, attempt_id)
    current_b = _product_session(token=derived_b, ledger_id="family", role="viewer")
    sessions, recoveries, store = _stores(current_b)
    recoveries[_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        account_name="我",
        ledger_id="family",
        ledger_name="家庭账本",
        device_name="小票夹 Desktop",
        role="viewer",
        activation_expires_at=_STAGED_EXPIRY,
        superseded_session_token="tbx-old-A",
    )
    revoked: list[str] = []
    pending_c = _pending_for(ledger_id="third", role="member")

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=lambda *_args, **_kwargs: pending_c,
        product_session_activator=_activate_pending,
        product_session_revoker=lambda _origin, token, **_kwargs: revoked.append(token),
        **store,
    )

    projection = controller.switch_product_principal_ledger("third")

    assert projection["ledger_id"] == "third"
    assert revoked[0] == "tbx-old-A"
    assert recoveries == {}


# ── Round-6: revoke-scope split — switch cleanup never suicides the successor ──


def test_switch_cleanup_revokes_predecessor_without_lineage_scope() -> None:
    current = _product_session(ledger_id="owner")
    pending = _pending_for(ledger_id="family", role="viewer")
    sessions, _recoveries, store = _stores(current)
    calls: list[tuple[str, dict]] = []

    def capture_revoker(_origin, token, **kwargs) -> None:
        calls.append((token, kwargs))

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_ledger_switcher=lambda *_args, **_kwargs: pending,
        product_session_activator=_activate_pending,
        product_session_revoker=capture_revoker,
        **store,
    )

    projection = controller.switch_product_principal_ledger("family")

    assert projection["ledger_id"] == "family"
    # The switch cleanup retires the predecessor ONLY (no lineage scope) —
    # the promoted successor must stay the live session.
    assert [token for token, _ in calls] == [current.session_token]
    assert all(kwargs.get("scope") is None for _, kwargs in calls)


def test_unpair_revokes_with_lineage_scope() -> None:
    current = _product_session()
    sessions, _recoveries, store = _stores(current)
    calls: list[tuple[str, dict]] = []

    def capture_revoker(_origin, token, **kwargs) -> None:
        calls.append((token, kwargs))

    controller = AppController(
        FakeRuntime(),
        _config(),
        product_session_revoker=capture_revoker,
        **store,
    )

    assert controller.unpair_product_principal() == {"configured": False}
    # Teardown takes the whole staged/promoted lineage down.
    assert [token for token, _ in calls] == [current.session_token]
    assert all(kwargs.get("scope") == "lineage" for _, kwargs in calls)
