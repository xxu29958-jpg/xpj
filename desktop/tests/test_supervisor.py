"""BackendSupervisor lifecycle contract — the two correctness rules, with injected fakes.

No real subprocess is spawned: spawn / tree-kill / health / clock are all
fakes, so the test asserts the SUPERVISION LOGIC (no orphans, health-aware restart,
manual-stop-stays-stopped) deterministically.
"""

from __future__ import annotations

import threading
import time

import pytest

from backend_manager.supervisor import BackendSupervisor, SupervisorConfig, SupervisorControlError


class FakeProc:
    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._exit: int | None = None

    @property
    def pid(self) -> int:
        return self._pid

    def poll(self) -> int | None:
        return self._exit

    def die(self, code: int = 1) -> None:
        self._exit = code

    def recent_log(self) -> list[str]:
        return [f"proc {self._pid} log"]

    def wait(self, timeout: float) -> int:
        if self._exit is None:
            raise TimeoutError(f"still alive after {timeout}")
        return self._exit


class Harness:
    def __init__(self) -> None:
        self.spawned: list[FakeProc] = []
        self.tree_killed: list[int] = []
        self.kill_succeeds = True
        self.kill_results: list[bool] = []
        # No backend is serving until the supervisor spawns one (or a test sets
        # this True to model an already-running external backend to adopt).
        self.healthy = False
        self._now = 1000.0
        self._next_pid = 100

    def spawn(self) -> FakeProc:
        proc = FakeProc(self._next_pid)
        self._next_pid += 1
        self.spawned.append(proc)
        return proc

    def tree_kill(self, pid: int) -> bool:
        self.tree_killed.append(pid)
        succeeds = self.kill_results.pop(0) if self.kill_results else self.kill_succeeds
        if succeeds:
            next(proc for proc in self.spawned if proc.pid == pid).die(-9)
        return succeeds

    def health(self) -> bool:
        return self.healthy

    def clock(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    def build(self, **config: float) -> BackendSupervisor:
        return BackendSupervisor(
            spawn=self.spawn,
            tree_kill=self.tree_kill,
            health=self.health,
            clock=self.clock,
            config=SupervisorConfig(**config),
        )


def test_start_spawns_when_no_backend_is_serving() -> None:
    h = Harness()  # nothing healthy on the port
    sup = h.build()
    sup.start()
    assert len(h.spawned) == 1
    assert sup.status().running is True


def test_start_adopts_an_already_healthy_backend() -> None:
    h = Harness()
    h.healthy = True  # a backend (e.g. the boot scheduled-task) is already serving on the port
    sup = h.build()
    sup.start()
    assert len(h.spawned) == 0, "must adopt the healthy backend, not spawn a duplicate that would fail to bind"
    assert h.tree_killed == []
    assert sup.status().running is True


def test_stop_of_adopted_backend_reports_that_external_process_is_not_controllable() -> None:
    h = Harness()
    h.healthy = True
    sup = h.build()
    sup.start()

    with pytest.raises(SupervisorControlError, match="外部启动"):
        sup.stop()

    assert sup.status().running is True
    assert h.tree_killed == []


def test_restart_of_adopted_backend_reports_that_external_process_is_not_controllable() -> None:
    h = Harness()
    h.healthy = True
    sup = h.build()
    sup.start()

    with pytest.raises(SupervisorControlError, match="外部启动"):
        sup.restart()

    assert sup.status().running is True
    assert h.tree_killed == []
    assert h.spawned == []


def test_recovered_external_backend_is_readopted_after_failed_takeover() -> None:
    h = Harness()
    h.healthy = True
    sup = h.build(unhealthy_restarts_after=2)
    sup.start()
    h.healthy = False

    sup.tick()
    sup.tick()
    owned = h.spawned[0]
    owned.die()
    h.healthy = True
    sup.tick()

    assert h.tree_killed == []
    assert len(h.spawned) == 1
    assert sup.status().running is True


def test_stop_tree_kills_so_no_worker_is_orphaned() -> None:
    h = Harness()
    sup = h.build()
    sup.start()
    pid = h.spawned[0].pid
    sup.stop()
    assert pid in h.tree_killed, "stop must tree-kill (parent + worker), not orphan the worker"
    assert sup.status().running is False
    # managed=False after a manual stop → the monitor must NOT bring it back.
    h.spawned[0].die()
    sup.tick()
    assert len(h.spawned) == 1, "manual stop stays stopped"


def test_failed_tree_kill_keeps_owned_process_and_reports_failure() -> None:
    h = Harness()
    h.kill_succeeds = False
    sup = h.build()
    sup.start()

    with pytest.raises(SupervisorControlError, match="停止后端失败"):
        sup.stop()

    assert sup.status().running is True
    assert len(h.spawned) == 1


def test_failed_tree_kill_with_dead_parent_adopts_surviving_healthy_worker() -> None:
    h = Harness()
    h.kill_succeeds = False
    sup = h.build()
    sup.start()
    h.spawned[0].die()
    h.healthy = True

    with pytest.raises(SupervisorControlError, match="父进程已退出"):
        sup.stop()

    assert sup.status().running is True
    assert h.tree_killed == [100]


def test_monitor_survives_failed_automatic_restart_and_retries() -> None:
    h = Harness()
    h.kill_results = [False, True]
    sup = h.build(tick_seconds=0.005, health_grace_seconds=0, unhealthy_restarts_after=1)
    sup.start()
    h.healthy = False
    stop_event = threading.Event()
    monitor = threading.Thread(target=sup.run_monitor, args=(stop_event,))
    monitor.start()

    deadline = time.monotonic() + 1
    while len(h.spawned) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    stop_event.set()
    monitor.join(timeout=1)

    assert len(h.spawned) == 2
    assert sup.restarts == 1
    assert sup.status().control_error is None


def test_successful_manual_stop_clears_prior_monitor_error() -> None:
    h = Harness()
    h.kill_results = [False, True]
    sup = h.build(health_grace_seconds=0, unhealthy_restarts_after=1)
    sup.start()
    h.healthy = False

    with pytest.raises(SupervisorControlError):
        sup.tick()
    assert sup.status().control_error is not None

    sup.stop()

    assert sup.status().control_error is None


def test_crash_triggers_auto_restart() -> None:
    h = Harness()
    sup = h.build()
    sup.start()
    h.spawned[0].die()
    sup.tick()
    assert len(h.spawned) == 2, "a dead process is respawned"
    assert sup.restarts == 1


def test_auto_restart_off_does_not_revive_a_crash() -> None:
    h = Harness()
    sup = h.build()
    sup.start()
    sup.auto_restart = False
    h.spawned[0].die()
    sup.tick()
    assert len(h.spawned) == 1
    assert sup.restarts == 0


def test_unhealthy_within_grace_is_not_restarted() -> None:
    h = Harness()
    sup = h.build(health_grace_seconds=25.0)
    sup.start()
    h.healthy = False
    h.advance(10.0)  # still inside the first-boot grace window
    sup.tick()
    assert len(h.spawned) == 1, "first-boot migrations must not be mistaken for a hang"


def test_sustained_unhealthy_after_grace_restarts() -> None:
    h = Harness()
    sup = h.build(health_grace_seconds=25.0, unhealthy_restarts_after=2)
    sup.start()
    h.advance(30.0)  # past grace
    h.healthy = False
    sup.tick()  # streak 1 — not yet
    assert len(h.spawned) == 1
    sup.tick()  # streak 2 — restart
    assert len(h.spawned) == 2
    assert sup.restarts == 1


def test_recovered_health_resets_the_streak() -> None:
    h = Harness()
    sup = h.build(health_grace_seconds=25.0, unhealthy_restarts_after=2)
    sup.start()
    h.advance(30.0)
    h.healthy = False
    sup.tick()  # streak 1
    h.healthy = True
    sup.tick()  # streak reset
    h.healthy = False
    sup.tick()  # streak back to 1 — still no restart
    assert len(h.spawned) == 1
