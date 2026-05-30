"""BackendSupervisor lifecycle contract — the two correctness rules, with injected fakes.

No real subprocess is spawned: spawn / tree-kill / port-clear / health / clock are all
fakes, so the test asserts the SUPERVISION LOGIC (no orphans, health-aware restart,
manual-stop-stays-stopped) deterministically.
"""

from __future__ import annotations

from backend_manager.supervisor import BackendSupervisor, SupervisorConfig


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


class Harness:
    def __init__(self) -> None:
        self.spawned: list[FakeProc] = []
        self.tree_killed: list[int] = []
        self.port_cleared = 0
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

    def tree_kill(self, pid: int) -> None:
        self.tree_killed.append(pid)

    def kill_port(self) -> None:
        self.port_cleared += 1

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
            kill_port=self.kill_port,
            health=self.health,
            clock=self.clock,
            config=SupervisorConfig(**config),
        )


def test_start_spawns_when_no_backend_is_serving() -> None:
    h = Harness()  # nothing healthy on the port
    sup = h.build()
    sup.start()
    assert h.port_cleared == 0, "start must NOT blind-clear the port — never terminate an unowned process"
    assert len(h.spawned) == 1
    assert sup.status().running is True


def test_start_adopts_an_already_healthy_backend() -> None:
    h = Harness()
    h.healthy = True  # a backend (e.g. the boot scheduled-task) is already serving on the port
    sup = h.build()
    sup.start()
    assert len(h.spawned) == 0, "must adopt the healthy backend, not spawn a duplicate that would fail to bind"
    assert h.port_cleared == 0, "must never kill a healthy backend it does not own"
    assert h.tree_killed == []
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
