"""Stable UI status contract and user-visible control failures."""

from __future__ import annotations

import threading
from pathlib import Path

from backend_manager.app_controller import AppController
from backend_manager.config import ConfigError, InstalledRuntimeConfig, ManagerConfig, SourceRuntimeConfig
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.projection import RefreshingInstalledRuntimeConfigProvider
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
        runtime=SourceRuntimeConfig(Path("backend"), Path("python.exe")),
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


def test_control_failure_is_returned_then_cleared_after_success() -> None:
    runtime = FakeRuntime()
    controller = AppController(runtime, _config())
    runtime.fail_start = True

    controller.start()
    assert controller.status()["control_error"] == "需要管理员权限"

    runtime.fail_start = False
    controller.start()
    assert controller.status()["control_error"] is None


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
    assert controller.status()["public_endpoint_state"] == "protected_unknown"
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
