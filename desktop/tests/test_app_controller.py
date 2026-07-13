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


def test_mobile_tasks_fail_closed_when_backend_reports_local_only(monkeypatch) -> None:
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
    assert "尚未配置手机可达入口" in controller.status()["control_error"]
    controller.open_upload_links()
    assert "尚未配置 iPhone 上传入口" in controller.status()["control_error"]
    assert opened == []


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
