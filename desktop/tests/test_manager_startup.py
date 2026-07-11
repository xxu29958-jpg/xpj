"""Per-user Desktop Manager startup and bind coordination."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from backend_manager.__main__ import main
from backend_manager.config import ManagerConfig, SourceRuntimeConfig
from backend_manager.instance_owner import InstanceRegistration
from backend_manager.runtime import RuntimeControlError, RuntimeStatus


@contextmanager
def _manager_instance(*, owner: bool, secret: str = "instance-secret", promote: bool = False):
    class Instance:
        def __init__(self) -> None:
            self.is_owner = owner
            self.secret = secret if owner else None
            self.port = 8799 if owner else None

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
    monkeypatch.setattr("backend_manager.manager_startup.open_app_window", lambda _url: None)
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
    monkeypatch.setattr("backend_manager.manager_startup.probe_existing_manager", lambda _url, proof: proof == "instance-secret")
    monkeypatch.setattr("backend_manager.manager_startup.open_app_window", opened.append)
    monkeypatch.setattr(
        "backend_manager.manager_startup.build_provider",
        lambda _config: (_ for _ in ()).throw(AssertionError("must not build a second runtime")),
    )

    assert main([]) == 0
    assert opened == [f"{config.manager_url}?instance=instance-secret"]


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
    monkeypatch.setattr("backend_manager.manager_startup.probe_existing_manager", lambda _url, _proof: next(attempts))
    monkeypatch.setattr("backend_manager.manager_startup.open_app_window", opened.append)
    monkeypatch.setattr("backend_manager.manager_startup.time.sleep", lambda _seconds: None)

    assert main([]) == 0
    assert opened == [f"{config.manager_url}?instance=instance-secret"]


def test_second_launch_takes_released_mutex_when_first_instance_exits(monkeypatch) -> None:
    config = _config()
    promoted: list[str] = []
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        "backend_manager.manager_startup.claim_manager_instance",
        lambda: _manager_instance(owner=False, secret="replacement-proof", promote=True),
    )
    monkeypatch.setattr("backend_manager.manager_startup.probe_existing_manager", lambda *_args: False)
    monkeypatch.setattr(
        "backend_manager.manager_startup.run_owned_manager",
        lambda _config, instance: (promoted.append(instance.secret), 0)[-1],
    )

    assert main([]) == 0
    assert promoted == ["replacement-proof"]


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
    monkeypatch.setattr("backend_manager.manager_startup.open_app_window", opened.append)
    monkeypatch.setattr("backend_manager.manager_startup.time.sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt))

    assert main([]) == 0

    assert bind_ports == [8799, 0]
    assert opened == ["http://127.0.0.1:49152/?instance=instance-secret"]
