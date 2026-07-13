"""Per-user Desktop Manager startup and bind coordination."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from backend_manager.__main__ import main
from backend_manager.build_identity import FrozenManagerIdentity
from backend_manager.config import (
    ConfigError,
    MaintenanceManagerConfig,
    ManagerConfig,
    SourceRuntimeConfig,
)
from backend_manager.instance_owner import InstanceRegistration
from backend_manager.manager_startup import ManagerWindowSession, run_manager, run_owned_manager
from backend_manager.runtime import RuntimeControlError, RuntimeStatus


@contextmanager
def _manager_instance(*, owner: bool, secret: str = "instance-secret", promote: bool = False):
    with TemporaryDirectory(prefix="ticketbox-manager-test-") as temp_root:
        class Instance:
            def __init__(self) -> None:
                self.is_owner = owner
                self.secret = secret if owner else None
                self.port = 8799 if owner else None
                self.root = Path(temp_root)

            def read_secret(self) -> str | None:
                return secret

            def read_registration(self) -> InstanceRegistration:
                return InstanceRegistration(secret, self.port or 8799)

            def try_take_ownership(self) -> bool:
                if not promote:
                    return False
                self.is_owner = True
                self.secret = secret
                self.port = None
                return True

            def publish_port(self, port: int) -> None:
                self.port = port

        yield Instance()


class FakeWindow:
    def __init__(self, *, opened: bool = True) -> None:
        self.opened = opened

    def is_open(self) -> bool:
        return self.opened

    def close(self, *, timeout: float = 5.0) -> bool:
        self.opened = False
        return True


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


def test_window_session_gives_every_tracked_edge_process_its_own_profile(tmp_path: Path) -> None:
    profiles: list[Path] = []

    def open_window(_url: str, *, profile: Path) -> FakeWindow:
        profiles.append(profile)
        return FakeWindow()

    profile_root = tmp_path / "edge-session"
    windows = ManagerWindowSession(
        "http://127.0.0.1:8799/",
        profile_root,
        opener=open_window,
    )

    assert windows.open() is True
    assert windows.open() is True
    assert profiles == [
        profile_root / "window-0001",
        profile_root / "window-0002",
    ]
    assert windows.close_all() is True


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


def test_control_server_binds_before_source_start_and_all_exits_close_owned_runtime(monkeypatch) -> None:
    events: list[str] = []
    config = _config()

    class Runtime(FakeRuntime):
        def start(self) -> None:
            events.append("backend-start")

        def shutdown(self) -> None:
            events.append("runtime-shutdown")

    class Provider:
        mode_hint = "source"

        def __init__(self) -> None:
            self.runtime = Runtime()

        def current(self):
            from backend_manager.projection import RuntimeProjection

            return RuntimeProjection(config=config, runtime=self.runtime)

        def run_monitor(self, stop_event) -> None:
            stop_event.wait()

        def shutdown(self) -> None:
            self.runtime.shutdown()

    class Server:
        server_address = ("127.0.0.1", 8799)

        def __init__(self, *_args, **_kwargs) -> None:
            events.append("control-bind")

        def serve_forever(self) -> None:
            events.append("control-serve")

        def shutdown(self) -> None:
            events.append("control-shutdown")
            raise RuntimeError("simulated shutdown failure")

        def server_close(self) -> None:
            events.append("control-close")

    provider = Provider()
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: _manager_instance(owner=True),
    )
    monkeypatch.setattr("backend_manager.manager_startup.build_provider", lambda _config: provider)
    monkeypatch.setattr("backend_manager.manager_startup.ControlServer", Server)
    monkeypatch.setattr(
        "backend_manager.manager_startup.open_app_window",
        lambda _url, *, profile: FakeWindow(),
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.time.sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    assert main([]) == 0
    assert events.index("control-bind") < events.index("backend-start")
    assert "control-shutdown" in events
    assert "control-close" in events
    assert "runtime-shutdown" in events


def test_second_launch_reopens_existing_manager_without_starting_another_runtime(monkeypatch) -> None:
    config = _config()
    opened: list[str] = []
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: _manager_instance(owner=False),
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.request_existing_manager_window",
        lambda url, proof: (opened.append(url), proof == "instance-secret")[-1],
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.build_provider",
        lambda _config: (_ for _ in ()).throw(AssertionError("must not build a second runtime")),
    )

    assert main([]) == 0
    assert opened == [config.manager_url]


def test_second_launch_reports_window_open_failure(monkeypatch) -> None:
    config = _config()
    times = iter((0.0, 3.0))
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: _manager_instance(owner=False),
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.request_existing_manager_window",
        lambda _url, _proof: False,
    )
    monkeypatch.setattr("backend_manager.manager_startup.time.monotonic", lambda: next(times))
    monkeypatch.setattr("backend_manager.manager_startup.time.sleep", lambda _seconds: None)

    with pytest.raises(ConfigError, match="无法验证其控制界面"):
        main([])


def test_second_launch_waits_for_legitimate_owner_bind_race(monkeypatch) -> None:
    config = _config()
    opened: list[str] = []
    attempts = iter((False, True))
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: _manager_instance(owner=False),
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.request_existing_manager_window",
        lambda url, _proof: (opened.append(url), next(attempts))[-1],
    )
    monkeypatch.setattr("backend_manager.manager_startup.time.sleep", lambda _seconds: None)

    assert main([]) == 0
    assert opened == [config.manager_url, config.manager_url]


def test_second_launch_takes_released_mutex_when_first_instance_exits(monkeypatch) -> None:
    config = _config()
    promoted: list[str] = []
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: _manager_instance(owner=False, secret="replacement-proof", promote=True),
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.request_existing_manager_window",
        lambda *_args: False,
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.run_owned_manager",
        lambda _config, instance: (promoted.append(instance.secret), 0)[-1],
    )

    assert main([]) == 0
    assert promoted == ["replacement-proof"]


def test_frozen_manager_starts_restricted_maintenance_shell_when_install_config_is_broken(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "manager" / "ticketbox-manager.exe"
    started: list[MaintenanceManagerConfig] = []
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr(
        "backend_manager.__main__.load_config",
        lambda: (_ for _ in ()).throw(
            ConfigError("registry broken", code="registry_contract_invalid"),
        ),
    )
    monkeypatch.setattr(
        "backend_manager.__main__.load_frozen_manager_identity",
        lambda: FrozenManagerIdentity(executable, "1.2.0.7"),
    )
    monkeypatch.setattr(
        "backend_manager.__main__.load_maintenance_manager_config",
        lambda version, **kwargs: MaintenanceManagerConfig(
            "127.0.0.1",
            8799,
            version,
            **kwargs,
        ),
    )
    monkeypatch.setattr(
        "backend_manager.__main__.run_manager",
        lambda config: (started.append(config), 0)[-1],
    )

    assert main([]) == 0
    assert started == [
        MaintenanceManagerConfig(
            "127.0.0.1",
            8799,
            "1.2.0.7",
            startup_failure_code="registry_contract_invalid",
            startup_failure_stage="runtime_discovery",
        ),
    ]


def test_source_startup_error_does_not_forge_an_installed_maintenance_shell(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr(
        "backend_manager.__main__.load_config",
        lambda: (_ for _ in ()).throw(ConfigError("source venv missing")),
    )
    monkeypatch.setattr("backend_manager.__main__.load_frozen_manager_identity", lambda: None)

    with pytest.raises(ConfigError, match="source venv missing"):
        main([])


def test_signaled_installer_gate_blocks_manager_before_runtime_or_window(monkeypatch) -> None:
    config = MaintenanceManagerConfig("127.0.0.1", 8799, "1.2.0")
    monkeypatch.setattr(
        "backend_manager.manager_startup.ControlServer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not bind")),
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.open_app_window",
        lambda _url, *, profile: (_ for _ in ()).throw(AssertionError("must not open")),
    )

    with _manager_instance(owner=True) as instance:
        assert run_owned_manager(config, instance, maintenance_requested=lambda: True) == 0


def test_signaled_installer_gate_blocks_second_launch_before_claim(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend_manager.manager_startup.manager_maintenance_requested",
        lambda: True,
    )
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: (_ for _ in ()).throw(AssertionError("must not claim or reopen")),
    )

    assert run_manager(_config()) == 0


def test_last_visible_window_closes_manager_host(monkeypatch) -> None:
    events: list[str] = []
    config = MaintenanceManagerConfig("127.0.0.1", 8799, "1.2.0")

    class Server:
        server_address = ("127.0.0.1", 8799)

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def serve_forever(self) -> None:
            events.append("serve")

        def shutdown(self) -> None:
            events.append("server-shutdown")

        def server_close(self) -> None:
            events.append("server-close")

    monkeypatch.setattr("backend_manager.manager_startup.ControlServer", Server)
    monkeypatch.setattr(
        "backend_manager.manager_startup.open_app_window",
        lambda _url, *, profile: FakeWindow(opened=False),
    )
    with _manager_instance(owner=True) as instance:
        assert run_owned_manager(config, instance) == 0

    assert "server-shutdown" in events
    assert "server-close" in events


def test_external_maintenance_closes_edge_before_manager_server(monkeypatch) -> None:
    events: list[str] = []
    checks = iter((False, True))
    config = MaintenanceManagerConfig("127.0.0.1", 8799, "1.2.0")

    class Window(FakeWindow):
        def close(self, *, timeout: float = 5.0) -> bool:
            events.append("edge-close")
            return super().close(timeout=timeout)

    class Server:
        server_address = ("127.0.0.1", 8799)

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def serve_forever(self) -> None:
            events.append("serve")

        def shutdown(self) -> None:
            events.append("server-shutdown")

        def server_close(self) -> None:
            events.append("server-close")

    monkeypatch.setattr("backend_manager.manager_startup.ControlServer", Server)
    monkeypatch.setattr(
        "backend_manager.manager_startup.open_app_window",
        lambda _url, *, profile: Window(),
    )
    with _manager_instance(owner=True) as instance:
        assert (
            run_owned_manager(
                config,
                instance,
                maintenance_requested=lambda: next(checks),
            )
            == 0
        )

    assert events.index("edge-close") < events.index("server-shutdown")


def test_foreign_user_port_squatter_falls_back_without_opening_attacker_ui(monkeypatch) -> None:
    config = _config()
    opened: list[str] = []
    bind_ports: list[int] = []

    class Server:
        server_address = ("127.0.0.1", 49152)

        def __init__(self, _host: str, port: int, **_kwargs) -> None:
            bind_ports.append(port)
            if port == config.manager_port:
                raise OSError("port occupied by another user")

        def serve_forever(self) -> None:
            pass

        def shutdown(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: _manager_instance(owner=True),
    )
    monkeypatch.setattr("backend_manager.manager_startup.ControlServer", Server)
    monkeypatch.setattr(
        "backend_manager.manager_startup.open_app_window",
        lambda url, *, profile: (opened.append(url), FakeWindow())[-1],
    )
    monkeypatch.setattr("backend_manager.manager_startup.time.sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt))

    assert main([]) == 0

    assert bind_ports == [8799, 0]
    assert opened == ["http://127.0.0.1:49152/?instance=instance-secret"]
