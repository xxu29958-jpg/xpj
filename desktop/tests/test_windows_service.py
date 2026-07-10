"""Installed Windows-service runtime contracts with an in-memory SCM gateway."""

from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path

import pytest

from backend_manager.runtime import RuntimeControlError, ServiceAccessError
from backend_manager.windows_service import (
    BrokeredWindowsServiceRuntime,
    ServiceSnapshot,
    WindowsServiceGateway,
    WindowsServiceRuntime,
)


class FakeGateway:
    def __init__(self, *, backend: str = "stopped", database: str = "stopped") -> None:
        self.states = {"TicketboxBackend": backend, "TicketboxPg": database}
        self.actions: list[tuple[str, str]] = []

    def query(self, name: str) -> ServiceSnapshot:
        state = self.states.get(name, "missing")
        return ServiceSnapshot(name=name, state=state, pid=4321 if state == "running" else None)

    def start(self, name: str) -> None:
        self.actions.append(("start", name))
        self.states[name] = "running"

    def stop(self, name: str) -> None:
        self.actions.append(("stop", name))
        self.states[name] = "stopped"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeActionRunner:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def run(self, action: str) -> None:
        self.actions.append(action)


def _runtime(tmp_path: Path, gateway: FakeGateway, *, healthy: bool = True) -> WindowsServiceRuntime:
    return WindowsServiceRuntime(
        gateway=gateway,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_url="http://127.0.0.1:8000/api/health",
        log_path=tmp_path / "backend.log",
        health=lambda _url: healthy,
        poll_seconds=0,
    )


def test_status_reports_both_services_health_and_log_tail(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
    log_path = tmp_path / "backend.log"
    log_path.write_text("first\nready\n", encoding="utf-8")
    runtime = _runtime(tmp_path, gateway)

    status = runtime.status()

    assert status.mode == "installed"
    assert status.running is True
    assert status.healthy is True
    assert status.pid == 4321
    assert status.backend_service_state == "running"
    assert status.database_service_state == "running"
    assert status.auto_restart is True
    assert status.auto_restart_configurable is False
    assert status.log == ["first", "ready"]


def test_status_limits_log_to_latest_300_lines(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
    log_path = tmp_path / "backend.log"
    log_path.write_text("".join(f"line-{index}\n" for index in range(350)), encoding="utf-8")

    status = _runtime(tmp_path, gateway).status()

    assert len(status.log) == 300
    assert status.log[0] == "line-50"
    assert status.log[-1] == "line-349"


def test_start_brings_database_up_before_backend(tmp_path: Path) -> None:
    gateway = FakeGateway()
    runtime = _runtime(tmp_path, gateway)

    runtime.start()

    assert gateway.actions == [
        ("start", "TicketboxPg"),
        ("start", "TicketboxBackend"),
    ]


def test_stop_leaves_database_running(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
    runtime = _runtime(tmp_path, gateway)

    runtime.stop()

    assert gateway.actions == [("stop", "TicketboxBackend")]
    assert gateway.states["TicketboxPg"] == "running"


def test_restart_stops_backend_then_rechecks_database_before_start(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
    runtime = _runtime(tmp_path, gateway)

    runtime.restart()

    assert gateway.actions == [
        ("stop", "TicketboxBackend"),
        ("start", "TicketboxBackend"),
    ]


def test_restart_waits_out_existing_stop_pending_without_duplicate_control(tmp_path: Path) -> None:
    class PendingGateway(FakeGateway):
        def __init__(self) -> None:
            super().__init__(backend="stop_pending", database="running")
            self.backend_queries = 0

        def query(self, name: str) -> ServiceSnapshot:
            if name == "TicketboxBackend" and self.states[name] == "stop_pending":
                self.backend_queries += 1
                if self.backend_queries >= 2:
                    self.states[name] = "stopped"
            return super().query(name)

    gateway = PendingGateway()
    runtime = _runtime(tmp_path, gateway)

    runtime.restart()

    assert gateway.actions == [("start", "TicketboxBackend")]


@pytest.mark.parametrize(
    ("operation", "expected_actions"),
    [("stop", []), ("restart", [("start", "TicketboxBackend")])],
)
def test_control_accepts_start_pending_that_converges_to_stopped(
    tmp_path: Path,
    operation: str,
    expected_actions: list[tuple[str, str]],
) -> None:
    class StartThenStoppedGateway(FakeGateway):
        def __init__(self) -> None:
            super().__init__(backend="start_pending", database="running")
            self.backend_queries = 0

        def query(self, name: str) -> ServiceSnapshot:
            if name == "TicketboxBackend" and self.states[name] == "start_pending":
                self.backend_queries += 1
                if self.backend_queries >= 2:
                    self.states[name] = "stopped"
            return super().query(name)

    gateway = StartThenStoppedGateway()
    runtime = _runtime(tmp_path, gateway)

    getattr(runtime, operation)()

    assert gateway.actions == expected_actions


def test_missing_service_has_repair_guidance(tmp_path: Path) -> None:
    gateway = FakeGateway(database="missing")
    runtime = _runtime(tmp_path, gateway)

    with pytest.raises(RuntimeControlError, match="修复或重新安装"):
        runtime.start()


def test_start_timeout_reports_service_and_current_state(tmp_path: Path) -> None:
    class StuckGateway(FakeGateway):
        def start(self, name: str) -> None:
            self.actions.append(("start", name))

    clock = FakeClock()
    runtime = WindowsServiceRuntime(
        gateway=StuckGateway(),
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_url="http://127.0.0.1:8000/api/health",
        log_path=tmp_path / "backend.log",
        health=lambda _url: False,
        wait_timeout_seconds=1,
        pg_wait_timeout_seconds=1,
        poll_seconds=0.25,
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(RuntimeControlError, match=r"TicketboxPg.*1 秒.*stopped"):
        runtime.start()


def test_postgres_progress_can_continue_for_more_than_45_seconds(tmp_path: Path) -> None:
    clock = FakeClock()

    class SlowPgGateway(FakeGateway):
        def __init__(self) -> None:
            super().__init__()
            self.pg_started = False

        def start(self, name: str) -> None:
            self.actions.append(("start", name))
            if name == "TicketboxPg":
                self.pg_started = True
            else:
                self.states[name] = "running"

        def query(self, name: str) -> ServiceSnapshot:
            if name == "TicketboxPg" and self.pg_started:
                if clock.now >= 50:
                    return ServiceSnapshot(name=name, state="running", pid=100)
                return ServiceSnapshot(
                    name=name,
                    state="start_pending",
                    checkpoint=int(clock.now // 5) + 1,
                    wait_hint_ms=10_000,
                )
            return super().query(name)

    gateway = SlowPgGateway()
    runtime = WindowsServiceRuntime(
        gateway=gateway,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_url="http://127.0.0.1:8000/api/health",
        log_path=tmp_path / "backend.log",
        health=lambda _url: False,
        poll_seconds=1,
        clock=clock,
        sleep=clock.sleep,
    )

    runtime.start()

    assert clock.now >= 50
    assert gateway.actions == [("start", "TicketboxPg"), ("start", "TicketboxBackend")]


def test_blocked_health_probe_does_not_block_service_stop(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
    health_started = threading.Event()
    release_health = threading.Event()
    control_done = threading.Event()

    def blocked_health(_url: str) -> bool:
        health_started.set()
        release_health.wait(timeout=2)
        return False

    runtime = WindowsServiceRuntime(
        gateway=gateway,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_url="http://127.0.0.1:8000/api/health",
        log_path=tmp_path / "backend.log",
        health=blocked_health,
        poll_seconds=0,
    )
    status_thread = threading.Thread(target=runtime.status)
    status_thread.start()
    assert health_started.wait(timeout=1)

    control_thread = threading.Thread(target=lambda: (runtime.stop(), control_done.set()))
    control_thread.start()

    assert control_done.wait(timeout=0.5), "status health I/O must not hold the mutation lock"
    release_health.set()
    status_thread.join(timeout=1)
    control_thread.join(timeout=1)
    assert gateway.actions == [("stop", "TicketboxBackend")]


def test_log_permission_error_does_not_hide_service_status(tmp_path: Path, monkeypatch) -> None:
    gateway = FakeGateway(backend="running", database="running")

    def denied(_path: Path) -> bool:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "is_file", denied)

    status = _runtime(tmp_path, gateway).status()

    assert status.running is True
    assert status.database_service_state == "running"
    assert status.log == []


def test_status_access_denial_never_recommends_elevating_http_manager(tmp_path: Path) -> None:
    class DeniedGateway(FakeGateway):
        def query(self, name: str) -> ServiceSnapshot:
            raise ctypes.WinError(5)

    runtime = _runtime(tmp_path, DeniedGateway())

    with pytest.raises(ServiceAccessError) as error:
        runtime.status()

    assert "修复安装或服务权限" in str(error.value)
    assert "管理员身份运行" not in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows SCM API only exists on Windows")
def test_real_gateway_reports_unknown_service_as_missing() -> None:
    snapshot = WindowsServiceGateway().query("TicketboxDefinitelyMissingForContractTest")

    assert snapshot.state == "missing"


def test_brokered_runtime_delegates_mutations_without_direct_scm_write(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
    status_runtime = _runtime(tmp_path, gateway)
    runner = FakeActionRunner()
    runtime = BrokeredWindowsServiceRuntime(status_runtime, runner)

    runtime.stop()
    runtime.start()
    runtime.restart()

    assert runner.actions == ["stop", "start", "restart"]
    assert gateway.actions == []
    assert runtime.status().healthy is True
