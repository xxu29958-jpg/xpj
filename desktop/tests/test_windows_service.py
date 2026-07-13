"""Installed Windows-service runtime contracts with an in-memory SCM gateway."""

from __future__ import annotations

import ctypes
import json
import os
import threading
from pathlib import Path

import pytest

from backend_manager.installation import WindowsReleaseConfig
from backend_manager.process import HealthProbeResult, TicketboxHealthExpectation, _parse_health_payload
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


def _health_payload(
    *,
    installation_id: str = "ticketbox-0123456789abcdef0123456789abcdef",
    runtime_access_state: str = "available",
    owner_state: str = "configured",
    owner_recovery_channel: str = "managed_host",
) -> bytes:
    return json.dumps(
        {
            "contract": "ticketbox-installation-health-v2",
            "status": "ok",
            "product": "ticketbox",
            "backend_version": "9.8.7",
            "installation_id": installation_id,
            "runtime_access_state": runtime_access_state,
            "owner_state": owner_state,
            "owner_recovery_channel": owner_recovery_channel,
            "mobile_connectivity": {
                "mobile_endpoint_state": "local_only",
                "android_binding_state": "setup_required",
                "iphone_upload_state": "setup_required",
            },
        },
        separators=(",", ":"),
    ).encode()


def _runtime(
    tmp_path: Path,
    gateway: FakeGateway,
    *,
    healthy: bool = True,
    health_result: HealthProbeResult | None = None,
    backend_stopped_validator=None,
) -> WindowsServiceRuntime:
    result = health_result or HealthProbeResult(
        "healthy" if healthy else "pending",
        "verified" if healthy else "waiting",
    )
    return WindowsServiceRuntime(
        gateway=gateway,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_probe=lambda: result,
        wait_timeout_seconds=45,
        pg_wait_timeout_seconds=90,
        poll_seconds=0,
        backend_ready_timeout_seconds=120,
        backend_ready_poll_seconds=1,
        backend_stopped_validator=backend_stopped_validator,
    )


def test_status_reports_services_and_redacted_identity_health_without_raw_logs(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
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
    assert status.log[0] == "后端服务 TicketboxBackend：running，PID 4321"
    assert status.log[1] == "PostgreSQL服务 TicketboxPg：running，PID 4321"
    assert status.log[-1] == "日志状态：受保护；管理器不读取或显示后端原始日志。"
    assert status.health_state == "healthy"
    assert status.health_detail == "verified"


def test_health_json_requires_exact_product_version_and_installation_identity(tmp_path: Path) -> None:
    expectation = TicketboxHealthExpectation(
        backend_version="9.8.7",
        installation_id="ticketbox-0123456789abcdef0123456789abcdef",
    )
    random_200 = _parse_health_payload(b'{"status":"ok"}', expectation)
    valid = _parse_health_payload(_health_payload(), expectation)
    wrong_install = _parse_health_payload(
        _health_payload(installation_id="ticketbox-ffffffffffffffffffffffffffffffff"),
        expectation,
    )
    missing_owner = _parse_health_payload(
        _health_payload(owner_state="recovery_required"),
        expectation,
    )

    assert random_200.state == "mismatch"
    assert valid.healthy is True
    assert valid.mobile_endpoint_state == "local_only"
    assert valid.android_binding_state == "setup_required"
    assert valid.owner_state == "configured"
    assert wrong_install.state == "mismatch"
    assert missing_owner.healthy is True
    assert missing_owner.owner_state == "recovery_required"
    assert "缺少可用拥有者身份" in missing_owner.detail
    repair_required = _parse_health_payload(
        _health_payload(runtime_access_state="repair_required"),
        expectation,
    )
    assert repair_required.healthy is True
    assert repair_required.runtime_access_state == "repair_required"
    _runtime(
        tmp_path,
        FakeGateway(backend="running", database="running"),
        health_result=missing_owner,
    ).start()
    mismatch_status = _runtime(
        tmp_path,
        FakeGateway(backend="running", database="running"),
        health_result=wrong_install,
    ).status()
    pending_status = _runtime(
        tmp_path,
        FakeGateway(backend="running", database="running"),
        health_result=HealthProbeResult("pending", "listener not ready"),
    ).status()
    assert (mismatch_status.healthy, mismatch_status.health_state) == (False, "mismatch")
    assert (pending_status.healthy, pending_status.health_state) == (False, "pending")


@pytest.mark.parametrize("database_state", ["stopped", "missing", "stop_pending"])
def test_status_is_unhealthy_when_database_is_not_running(tmp_path: Path, database_state: str) -> None:
    probed = False

    def probe() -> HealthProbeResult:
        nonlocal probed
        probed = True
        return HealthProbeResult("healthy", "verified")

    runtime = _runtime(tmp_path, FakeGateway(backend="running", database=database_state))
    runtime._health_probe = probe  # noqa: SLF001 - prove DB failure short-circuits HTTP health

    status = runtime.status()

    assert status.running is True
    assert status.healthy is False
    assert database_state in status.health_detail
    assert "PostgreSQL" in status.health_detail
    assert probed is False


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
    runtime = _runtime(
        tmp_path,
        gateway,
        backend_stopped_validator=lambda: gateway.actions.append(("validate", "backend-runtime")),
    )

    runtime.restart()

    assert gateway.actions == [
        ("stop", "TicketboxBackend"),
        ("validate", "backend-runtime"),
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
        health_probe=lambda: HealthProbeResult("pending", "waiting"),
        wait_timeout_seconds=1,
        pg_wait_timeout_seconds=1,
        poll_seconds=0.25,
        backend_ready_timeout_seconds=1,
        backend_ready_poll_seconds=0.25,
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
        health_probe=lambda: HealthProbeResult("healthy", "verified"),
        wait_timeout_seconds=60,
        pg_wait_timeout_seconds=90,
        poll_seconds=1,
        backend_ready_timeout_seconds=120,
        backend_ready_poll_seconds=1,
        clock=clock,
        sleep=clock.sleep,
    )

    runtime.start()

    assert clock.now >= 50
    assert gateway.actions == [("start", "TicketboxPg"), ("start", "TicketboxBackend")]


def test_phase_budget_outlasts_full_reachable_restart_state_machine(tmp_path: Path) -> None:
    clock = FakeClock()
    release = WindowsReleaseConfig(
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        service_state_timeout_ms=2_000,
        service_poll_interval_ms=100,
        postgres_ready_timeout_ms=3_000,
        backend_ready_timeout_ms=4_000,
        backend_ready_poll_interval_ms=100,
        backend_health_request_timeout_ms=500,
    )

    class SlowTransitionGateway(FakeGateway):
        def __init__(self) -> None:
            super().__init__(backend="start_pending", database="stop_pending")
            self.deadlines: dict[str, float] = {}

        def _delay(self, name: str) -> float:
            return 2.8 if name == "TicketboxPg" else 1.8

        def query(self, name: str) -> ServiceSnapshot:
            state = self.states[name]
            if state in {"start_pending", "stop_pending"}:
                deadline = self.deadlines.setdefault(name, clock.now + self._delay(name))
                if clock.now >= deadline:
                    self.states[name] = "running" if state == "start_pending" else "stopped"
                    self.deadlines.pop(name, None)
            return ServiceSnapshot(
                name=name,
                state=self.states[name],
                pid=4321 if self.states[name] == "running" else None,
                checkpoint=int(clock.now * 10) + 1,
                wait_hint_ms=5_000,
            )

        def start(self, name: str) -> None:
            self.actions.append(("start", name))
            self.states[name] = "start_pending"
            self.deadlines[name] = clock.now + self._delay(name)

        def stop(self, name: str) -> None:
            self.actions.append(("stop", name))
            self.states[name] = "stop_pending"
            self.deadlines[name] = clock.now + self._delay(name)

    gateway = SlowTransitionGateway()
    health_started: float | None = None

    def health_probe() -> HealthProbeResult:
        nonlocal health_started
        if health_started is None:
            health_started = clock.now
        clock.sleep(0.45)
        if clock.now - health_started >= 3.5:
            return HealthProbeResult("healthy", "verified")
        return HealthProbeResult("pending", "warming")

    def validate_stopped() -> None:
        clock.sleep(1.8)
        # A separate SCM actor can begin a transition after validation. The
        # start path must still have budget for its own settle window.
        gateway.states["TicketboxBackend"] = "stop_pending"
        gateway.deadlines.pop("TicketboxBackend", None)

    runtime = WindowsServiceRuntime(
        gateway=gateway,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_probe=health_probe,
        wait_timeout_seconds=release.service_state_timeout_seconds,
        pg_wait_timeout_seconds=max(
            release.service_state_timeout_seconds,
            release.postgres_ready_timeout_seconds,
        ),
        poll_seconds=release.service_poll_seconds,
        backend_ready_timeout_seconds=release.backend_ready_timeout_seconds,
        backend_ready_poll_seconds=release.backend_ready_poll_seconds,
        clock=clock,
        sleep=clock.sleep,
        backend_stopped_validator=validate_stopped,
    )

    runtime.restart()

    action_phases = release.helper_action_phase_budget_seconds("restart")
    runtime_budget = sum(
        seconds
        for name, seconds in action_phases.items()
        if name not in {"pre_action_contract_validation", "watchdog_scheduler_margin"}
    )
    assert gateway.actions == [
        ("stop", "TicketboxBackend"),
        ("start", "TicketboxPg"),
        ("start", "TicketboxBackend"),
    ]
    assert clock.now > 15
    assert clock.now < runtime_budget < release.helper_watchdog_seconds("restart")


def test_blocked_health_probe_does_not_block_service_stop(tmp_path: Path) -> None:
    gateway = FakeGateway(backend="running", database="running")
    health_started = threading.Event()
    release_health = threading.Event()
    control_done = threading.Event()

    def blocked_health() -> HealthProbeResult:
        health_started.set()
        release_health.wait(timeout=2)
        return HealthProbeResult("pending", "waiting")

    runtime = WindowsServiceRuntime(
        gateway=gateway,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_probe=blocked_health,
        wait_timeout_seconds=45,
        pg_wait_timeout_seconds=90,
        poll_seconds=0,
        backend_ready_timeout_seconds=120,
        backend_ready_poll_seconds=1,
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


def test_status_never_opens_protected_backend_log(tmp_path: Path, monkeypatch) -> None:
    gateway = FakeGateway(backend="running", database="running")

    def denied(*_args, **_kwargs):
        raise AssertionError("ordinary GUI attempted to open a protected backend log")

    monkeypatch.setattr(Path, "open", denied)

    status = _runtime(tmp_path, gateway).status()

    assert status.running is True
    assert status.database_service_state == "running"
    assert status.log[-1] == "日志状态：受保护；管理器不读取或显示后端原始日志。"


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
