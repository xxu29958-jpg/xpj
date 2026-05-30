"""Backend process supervision — owns exactly one uvicorn process and keeps it alive.

The OS-touching operations (spawn / tree-kill / port-clear / health probe / clock)
are injected so the lifecycle logic is unit-testable without real subprocesses.

Two correctness rules this module exists to enforce:

* **No orphaned workers.** uvicorn spawns a child worker; on Windows, killing only
  the parent leaves the worker bound to the port. Termination therefore tree-kills
  (parent + descendants), so a "stop" actually frees the port.
* **Health-aware restart.** A crash (parent exits) restarts immediately; a hung or
  worker-dead process (parent alive but ``/api/health`` failing) restarts after a
  startup grace window and a few consecutive unhealthy probes, so first-boot
  migrations are not mistaken for a hang.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol


class ManagedProcess(Protocol):
    """A spawned backend process the supervisor owns."""

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None:
        """Return the exit code, or ``None`` while still running."""
        ...

    def recent_log(self) -> list[str]:
        """Most recent captured stdout/stderr lines (newest last)."""
        ...


# Injected callable signatures (real implementations live in ``process.py``).
SpawnFn = "callable[[], ManagedProcess]"
TreeKillFn = "callable[[int], None]"
KillPortFn = "callable[[], None]"
HealthFn = "callable[[], bool]"
ClockFn = "callable[[], float]"


@dataclass(frozen=True)
class SupervisorConfig:
    """Timing knobs for the supervision loop."""

    tick_seconds: float = 3.0
    health_grace_seconds: float = 25.0  # first boot runs migrations; don't mistake for a hang
    unhealthy_restarts_after: int = 2  # consecutive failing probes (post-grace) before restart


@dataclass(frozen=True)
class SupervisorStatus:
    """Read-only snapshot for the UI / control surface."""

    running: bool
    healthy: bool
    pid: int | None
    uptime_seconds: int
    auto_restart: bool
    restarts: int
    log: list[str]


class BackendSupervisor:
    """Owns one backend process; tree-kills it cleanly and restarts it when it dies."""

    def __init__(
        self,
        *,
        spawn,
        tree_kill,
        kill_port,
        health,
        config: SupervisorConfig | None = None,
        clock=time.monotonic,
    ) -> None:
        self._spawn = spawn
        self._tree_kill = tree_kill
        self._kill_port = kill_port
        self._health = health
        self._clock = clock
        self._config = config or SupervisorConfig()

        self._lock = threading.RLock()
        self._proc: ManagedProcess | None = None
        self._managed = False  # user intent: True means "should be running" (drives auto-restart)
        self._spawned_at: float | None = None
        self._unhealthy_streak = 0
        self._adopted = False  # tracking an externally-started healthy backend (we don't own its pid)

        self.auto_restart = True
        self.restarts = 0

    # ---- intent-driven controls ------------------------------------------
    def start(self) -> None:
        """Bring the backend up — or adopt one that is already healthy.

        We never kill a process we did not spawn. If a backend is already
        answering ``/api/health`` on the port (the boot scheduled-task, or a
        prior manager whose uvicorn worker outlived it), we ADOPT it: monitor
        its health but leave its process alone. We also never blind-clear the
        port — if some unrelated process holds it, uvicorn fails to bind and
        surfaces that in the log rather than us terminating an unknown process.
        """
        with self._lock:
            self._managed = True
            if self._alive():
                return
            if self._health():
                self._adopt()
                return
            self._adopted = False
            self._launch()

    def _adopt(self) -> None:
        """Track an externally-started, already-healthy backend (no owned pid)."""
        self._adopted = True
        self._proc = None
        self._spawned_at = None
        self._unhealthy_streak = 0

    def stop(self) -> None:
        """Tree-kill the backend and stop supervising it (no auto-restart)."""
        with self._lock:
            self._managed = False
            self._terminate()

    def restart(self) -> None:
        """Tree-kill and respawn a fresh backend."""
        with self._lock:
            self._managed = True
            self._terminate()
            self._kill_port()
            self._launch()

    # ---- supervision tick (called by the monitor thread or tests) --------
    def tick(self) -> None:
        """One supervision step: restart the backend if it has died or gone unhealthy."""
        with self._lock:
            if not (self._managed and self.auto_restart):
                return
            if self._adopted:
                # An externally-started backend we adopted. Sustained health
                # failure (past grace) means it's effectively gone — _check_health
                # takes over with our own process via _restart_internal.
                self._check_health()
                return
            if not self._alive():
                self._restart_internal()
                return
            self._check_health()

    def _check_health(self) -> None:
        if self._within_grace():
            return
        if self._health():
            self._unhealthy_streak = 0
            return
        self._unhealthy_streak += 1
        if self._unhealthy_streak >= self._config.unhealthy_restarts_after:
            self._restart_internal()

    def _within_grace(self) -> bool:
        return (
            self._spawned_at is not None
            and self._clock() - self._spawned_at < self._config.health_grace_seconds
        )

    # ---- process primitives ----------------------------------------------
    def _launch(self) -> None:
        self._proc = self._spawn()
        self._spawned_at = self._clock()
        self._unhealthy_streak = 0

    def _terminate(self) -> None:
        if self._proc is not None:
            self._tree_kill(self._proc.pid)
        self._proc = None
        self._spawned_at = None

    def _restart_internal(self) -> None:
        self.restarts += 1
        owned = self._proc is not None  # only clear the port for a backend we spawned
        self._adopted = False
        self._terminate()
        if owned:
            # Clear our own backend's worker residue (we just tree-killed its
            # parent). When taking over a now-unhealthy ADOPTED backend we own
            # nothing, so we never port-kill it — uvicorn surfaces a bind error
            # instead if that process is still holding the port.
            self._kill_port()
        self._launch()

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---- status -----------------------------------------------------------
    def status(self) -> SupervisorStatus:
        with self._lock:
            alive = self._alive()
            running = alive or self._adopted
            uptime = int(self._clock() - self._spawned_at) if (alive and self._spawned_at) else 0
            return SupervisorStatus(
                running=running,
                healthy=running and self._health(),
                pid=self._proc.pid if (alive and self._proc) else None,
                uptime_seconds=uptime,
                auto_restart=self.auto_restart,
                restarts=self.restarts,
                log=(self._proc.recent_log() if self._proc else []),
            )

    def toggle_auto_restart(self) -> bool:
        with self._lock:
            self.auto_restart = not self.auto_restart
            return self.auto_restart

    def run_monitor(self, stop_event: threading.Event) -> None:
        """Block in the supervision loop until ``stop_event`` is set (run in a daemon thread)."""
        while not stop_event.wait(self._config.tick_seconds):
            self.tick()
